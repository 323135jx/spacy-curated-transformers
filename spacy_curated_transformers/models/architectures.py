from functools import partial
from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple, Union, cast

import torch
from curated_transformers.models.albert import AlbertConfig, AlbertEncoder
from curated_transformers.models.bert import BertConfig, BertEncoder
from curated_transformers.models.curated_transformer import (
    CuratedEncoderT,
    CuratedTransformer,
)
from curated_transformers.models.hf_util import convert_pretrained_model_for_encoder
from curated_transformers.models.output import PyTorchTransformerOutput
from curated_transformers.models.roberta import RobertaConfig, RobertaEncoder
from spacy.tokens import Doc
from spacy.util import SimpleFrozenDict
from thinc.api import (
    Model,
    PyTorchWrapper_v2,
    TorchScriptWrapper_v1,
    get_torch_default_device,
    torch2xp,
    xp2torch,
)
from thinc.layers import chain
from thinc.model import Model
from thinc.shims.pytorch_grad_scaler import PyTorchGradScaler
from thinc.types import ArgsKwargs, Floats2d, Ints1d

from ..tokenization.types import Tok2PiecesModelT
from .listeners import (
    WrappedTransformerAndListener,
    replace_listener_callback,
    replace_listener_cfg_callback,
)
from .output import TransformerModelOutput
from .remove_eos_bos import remove_bos_eos
from .types import (
    SpanExtractorModelT,
    TorchTransformerInT,
    TorchTransformerModelT,
    TorchTransformerOutT,
    TransformerBackpropT,
    TransformerInT,
    TransformerListenerModelT,
    TransformerModelT,
    TransformerOutT,
    WrappedTransformerAndListenerModelT,
)
from .with_non_ws_tokens import with_non_ws_tokens


def build_albert_transformer_model_v1(
    *,
    vocab_size: int,
    with_spans: Callable[
        [TorchTransformerModelT],
        SpanExtractorModelT,
    ],
    piece_encoder: Tok2PiecesModelT,
    attention_probs_dropout_prob: float = 0.0,
    embedding_width: int = 128,
    hidden_act: str = "gelu_new",
    hidden_dropout_prob: float = 0.0,
    hidden_width: int = 768,
    intermediate_width: int = 3072,
    layer_norm_eps: float = 1e-12,
    max_position_embeddings: int = 512,
    model_max_length: int = 512,
    num_attention_heads: int = 12,
    num_hidden_groups: int = 1,
    num_hidden_layers: int = 12,
    padding_idx: int = 0,
    type_vocab_size: int = 2,
    torchscript: bool = False,
    mixed_precision: bool = False,
    grad_scaler_config: dict = SimpleFrozenDict(),
    wrapped_listener: Optional[TransformerListenerModelT] = None,
) -> Union[TransformerModelT, WrappedTransformerAndListenerModelT]:
    """Construct an ALBERT transformer model.

    vocab_size (int):
        Vocabulary size.
    with_spans (Callable):
        Callback that constructs a span generator model.
    piece_encoder (Model)
        The piece encoder to segment input tokens.
    attention_probs_dropout_prob (float):
        Dropout probabilty of the self-attention layers.
    embedding_width (int):
        Width of the embedding representations.
    hidden_act (str):
        Activation used by the point-wise feed-forward layers.
    hidden_dropout_prob (float):
        Dropout probabilty of the point-wise feed-forward and
        embedding layers.
    hidden_width (int):
        Width of the final representations.
    intermediate_width (int):
        Width of the intermediate projection layer in the
        point-wise feed-forward layer.
    layer_norm_eps (float):
        Epsilon for layer normalization.
    max_position_embeddings (int):
        Maximum length of position embeddings.
    model_max_length (int):
        Maximum length of model inputs.
    num_attention_heads (int):
        Number of self-attention heads.
    num_hidden_groups (int):
        Number of layer groups whose constituents share parameters.
    num_hidden_layers (int):
        Number of hidden layers.
    padding_idx (int):
        Index of the padding meta-token.
    type_vocab_size (int):
        Type vocabulary size.
    torchscript (bool):
        Set to `True` when loading TorchScript models, `False` otherwise.
    mixed_precision (bool):
        Use mixed-precision training.
    grad_scaler_config (dict):
        Configuration passed to the PyTorch gradient scaler.
    wrapped_listener (Optional[TransformerListenerModelT]):
        Optional listener to wrap. Only used when replacing listeners
        in downstream components.
    """
    config = AlbertConfig(
        embedding_width=embedding_width,
        hidden_width=hidden_width,
        intermediate_width=intermediate_width,
        num_attention_heads=num_attention_heads,
        num_hidden_groups=num_hidden_groups,
        num_hidden_layers=num_hidden_layers,
        attention_probs_dropout_prob=attention_probs_dropout_prob,
        hidden_dropout_prob=hidden_dropout_prob,
        hidden_act=hidden_act,
        vocab_size=vocab_size,
        type_vocab_size=type_vocab_size,
        max_position_embeddings=max_position_embeddings,
        model_max_length=model_max_length,
        layer_norm_eps=layer_norm_eps,
        padding_idx=padding_idx,
    )

    if torchscript:
        transformer = _torchscript_encoder(
            model_max_length=model_max_length, padding_idx=padding_idx
        )
    else:
        encoder = AlbertEncoder(config)
        transformer = _pytorch_encoder(
            encoder,
            hidden_width=hidden_width,
            mixed_precision=mixed_precision,
            grad_scaler_config=grad_scaler_config,
        )

    return build_transformer_or_listener_wrapper_v1(
        with_spans=with_spans,
        piece_encoder=piece_encoder,
        transformer=transformer,
        wrapped_listener=wrapped_listener,
    )


def build_bert_transformer_model_v1(
    *,
    vocab_size: int,
    with_spans: Callable[
        [TorchTransformerModelT],
        SpanExtractorModelT,
    ],
    piece_encoder: Tok2PiecesModelT,
    attention_probs_dropout_prob: float = 0.1,
    hidden_act: str = "gelu",
    hidden_dropout_prob: float = 0.1,
    hidden_width: int = 768,
    intermediate_width: int = 3072,
    layer_norm_eps: float = 1e-12,
    max_position_embeddings: int = 512,
    model_max_length: int = 512,
    num_attention_heads: int = 12,
    num_hidden_layers: int = 12,
    padding_idx: int = 0,
    type_vocab_size: int = 2,
    torchscript: bool = False,
    mixed_precision: bool = False,
    grad_scaler_config: dict = SimpleFrozenDict(),
    wrapped_listener: Optional[TransformerListenerModelT] = None,
) -> Union[TransformerModelT, WrappedTransformerAndListenerModelT]:
    """Construct a BERT transformer model.

    vocab_size (int):
        Vocabulary size.
    with_spans (Callable):
        Callback that constructs a span generator model.
    piece_encoder (Model)
        The piece encoder to segment input tokens.
    attention_probs_dropout_prob (float):
        Dropout probabilty of the self-attention layers.
    hidden_act (str):
        Activation used by the point-wise feed-forward layers.
    hidden_dropout_prob (float):
        Dropout probabilty of the point-wise feed-forward and
        embedding layers.
    hidden_width (int):
        Width of the final representations.
    intermediate_width (int):
        Width of the intermediate projection layer in the
        point-wise feed-forward layer.
    layer_norm_eps (float):
        Epsilon for layer normalization.
    max_position_embeddings (int):
        Maximum length of position embeddings.
    model_max_length (int):
        Maximum length of model inputs.
    num_attention_heads (int):
        Number of self-attention heads.
    num_hidden_layers (int):
        Number of hidden layers.
    padding_idx (int):
        Index of the padding meta-token.
    type_vocab_size (int):
        Type vocabulary size.
    torchscript (bool):
        Set to `True` when loading TorchScript models, `False` otherwise.
    mixed_precision (bool):
        Use mixed-precision training.
    grad_scaler_config (dict):
        Configuration passed to the PyTorch gradient scaler.
    wrapped_listener (Optional[TransformerListenerModelT]):
        Optional listener to wrap. Only used when replacing listeners
        in downstream components.
    """
    config = BertConfig(
        embedding_width=hidden_width,
        hidden_width=hidden_width,
        intermediate_width=intermediate_width,
        num_attention_heads=num_attention_heads,
        num_hidden_layers=num_hidden_layers,
        attention_probs_dropout_prob=attention_probs_dropout_prob,
        hidden_dropout_prob=hidden_dropout_prob,
        hidden_act=hidden_act,
        vocab_size=vocab_size,
        type_vocab_size=type_vocab_size,
        max_position_embeddings=max_position_embeddings,
        model_max_length=model_max_length,
        layer_norm_eps=layer_norm_eps,
        padding_idx=padding_idx,
    )

    if torchscript:
        transformer = _torchscript_encoder(
            model_max_length=model_max_length, padding_idx=padding_idx
        )
    else:
        encoder = BertEncoder(config)
        transformer = _pytorch_encoder(
            encoder,
            hidden_width=hidden_width,
            mixed_precision=mixed_precision,
            grad_scaler_config=grad_scaler_config,
        )

    return build_transformer_or_listener_wrapper_v1(
        with_spans=with_spans,
        piece_encoder=piece_encoder,
        transformer=transformer,
        wrapped_listener=wrapped_listener,
    )


def build_camembert_transformer_model_v1(
    *,
    vocab_size: int,
    with_spans: Callable[
        [TorchTransformerModelT],
        SpanExtractorModelT,
    ],
    piece_encoder: Tok2PiecesModelT,
    attention_probs_dropout_prob: float = 0.1,
    hidden_act: str = "gelu",
    hidden_dropout_prob: float = 0.1,
    hidden_width: int = 768,
    intermediate_width: int = 3072,
    layer_norm_eps: float = 1e-5,
    max_position_embeddings: int = 514,
    model_max_length: int = 512,
    num_attention_heads: int = 12,
    num_hidden_layers: int = 12,
    padding_idx: int = 1,
    type_vocab_size: int = 1,
    mixed_precision: bool = False,
    torchscript=False,
    grad_scaler_config: dict = SimpleFrozenDict(),
    wrapped_listener: Optional[TransformerListenerModelT] = None,
) -> Union[TransformerModelT, WrappedTransformerAndListenerModelT]:
    """Construct a CamemBERT transformer model.

    vocab_size (int):
        Vocabulary size.
    with_spans (Callable):
        Callback that constructs a span generator model.
    piece_encoder (Model)
        The piece encoder to segment input tokens.
    attention_probs_dropout_prob (float):
        Dropout probabilty of the self-attention layers.
    hidden_act (str):
        Activation used by the point-wise feed-forward layers.
    hidden_dropout_prob (float):
        Dropout probabilty of the point-wise feed-forward and
        embedding layers.
    hidden_width (int):
        Width of the final representations.
    intermediate_width (int):
        Width of the intermediate projection layer in the
        point-wise feed-forward layer.
    layer_norm_eps (float):
        Epsilon for layer normalization.
    max_position_embeddings (int):
        Maximum length of position embeddings.
    model_max_length (int):
        Maximum length of model inputs.
    num_attention_heads (int):
        Number of self-attention heads.
    num_hidden_layers (int):
        Number of hidden layers.
    padding_idx (int):
        Index of the padding meta-token.
    type_vocab_size (int):
        Type vocabulary size.
    torchscript (bool):
        Set to `True` when loading TorchScript models, `False` otherwise.
    mixed_precision (bool):
        Use mixed-precision training.
    grad_scaler_config (dict):
        Configuration passed to the PyTorch gradient scaler.
    wrapped_listener (Optional[TransformerListenerModelT]):
        Optional listener to wrap. Only used when replacing listeners
        in downstream components.
    """
    config = RobertaConfig(
        embedding_width=hidden_width,
        hidden_width=hidden_width,
        intermediate_width=intermediate_width,
        num_attention_heads=num_attention_heads,
        num_hidden_layers=num_hidden_layers,
        attention_probs_dropout_prob=attention_probs_dropout_prob,
        hidden_dropout_prob=hidden_dropout_prob,
        hidden_act=hidden_act,
        vocab_size=vocab_size,
        type_vocab_size=type_vocab_size,
        max_position_embeddings=max_position_embeddings,
        model_max_length=model_max_length,
        layer_norm_eps=layer_norm_eps,
        padding_idx=padding_idx,
    )

    if torchscript:
        transformer = _torchscript_encoder(
            model_max_length=model_max_length, padding_idx=padding_idx
        )
    else:
        encoder = RobertaEncoder(config)
        transformer = _pytorch_encoder(
            encoder,
            hidden_width=hidden_width,
            mixed_precision=mixed_precision,
            grad_scaler_config=grad_scaler_config,
        )

    return build_transformer_or_listener_wrapper_v1(
        with_spans=with_spans,
        piece_encoder=piece_encoder,
        transformer=transformer,
        wrapped_listener=wrapped_listener,
    )


def build_roberta_transformer_model_v1(
    *,
    vocab_size: int,
    with_spans: Callable[
        [TorchTransformerModelT],
        SpanExtractorModelT,
    ],
    piece_encoder: Tok2PiecesModelT,
    attention_probs_dropout_prob: float = 0.1,
    hidden_act: str = "gelu",
    hidden_dropout_prob: float = 0.1,
    hidden_width: int = 768,
    intermediate_width: int = 3072,
    layer_norm_eps: float = 1e-5,
    max_position_embeddings: int = 514,
    model_max_length: int = 512,
    num_attention_heads: int = 12,
    num_hidden_layers: int = 12,
    padding_idx: int = 1,
    type_vocab_size: int = 1,
    torchscript: bool = False,
    mixed_precision: bool = False,
    grad_scaler_config: dict = SimpleFrozenDict(),
    wrapped_listener: Optional[TransformerListenerModelT] = None,
) -> Union[TransformerModelT, WrappedTransformerAndListenerModelT]:
    """Construct a RoBERTa transformer model.

    vocab_size (int):
        Vocabulary size.
    with_spans (Callable):
        Callback that constructs a span generator model.
    piece_encoder (Model)
        The piece encoder to segment input tokens.
    attention_probs_dropout_prob (float):
        Dropout probabilty of the self-attention layers.
    hidden_act (str):
        Activation used by the point-wise feed-forward layers.
    hidden_dropout_prob (float):
        Dropout probabilty of the point-wise feed-forward and
        embedding layers.
    hidden_width (int):
        Width of the final representations.
    intermediate_width (int):
        Width of the intermediate projection layer in the
        point-wise feed-forward layer.
    layer_norm_eps (float):
        Epsilon for layer normalization.
    max_position_embeddings (int):
        Maximum length of position embeddings.
    model_max_length (int):
        Maximum length of model inputs.
    num_attention_heads (int):
        Number of self-attention heads.
    num_hidden_layers (int):
        Number of hidden layers.
    padding_idx (int):
        Index of the padding meta-token.
    type_vocab_size (int):
        Type vocabulary size.
    torchscript (bool):
        Set to `True` when loading TorchScript models, `False` otherwise.
    mixed_precision (bool):
        Use mixed-precision training.
    grad_scaler_config (dict):
        Configuration passed to the PyTorch gradient scaler.
    wrapped_listener (Optional[TransformerListenerModelT]):
        Optional listener to wrap. Only used when replacing listeners
        in downstream components.
    """
    config = RobertaConfig(
        embedding_width=hidden_width,
        hidden_width=hidden_width,
        intermediate_width=intermediate_width,
        num_attention_heads=num_attention_heads,
        num_hidden_layers=num_hidden_layers,
        attention_probs_dropout_prob=attention_probs_dropout_prob,
        hidden_dropout_prob=hidden_dropout_prob,
        hidden_act=hidden_act,
        vocab_size=vocab_size,
        type_vocab_size=type_vocab_size,
        max_position_embeddings=max_position_embeddings,
        model_max_length=model_max_length,
        layer_norm_eps=layer_norm_eps,
        padding_idx=padding_idx,
    )

    if torchscript:
        transformer = _torchscript_encoder(
            model_max_length=model_max_length, padding_idx=padding_idx
        )
    else:
        encoder = RobertaEncoder(config)
        transformer = _pytorch_encoder(
            encoder,
            hidden_width=hidden_width,
            mixed_precision=mixed_precision,
            grad_scaler_config=grad_scaler_config,
        )

    return build_transformer_or_listener_wrapper_v1(
        with_spans=with_spans,
        piece_encoder=piece_encoder,
        transformer=transformer,
        wrapped_listener=wrapped_listener,
    )


def build_xlmr_transformer_model_v1(
    *,
    vocab_size: int,
    with_spans: Callable[
        [TorchTransformerModelT],
        SpanExtractorModelT,
    ],
    piece_encoder: Tok2PiecesModelT,
    attention_probs_dropout_prob: float = 0.1,
    hidden_act: str = "gelu",
    hidden_dropout_prob: float = 0.1,
    hidden_width: int = 768,
    intermediate_width: int = 3072,
    layer_norm_eps: float = 1e-5,
    max_position_embeddings: int = 514,
    model_max_length: int = 512,
    num_attention_heads: int = 12,
    num_hidden_layers: int = 12,
    padding_idx: int = 1,
    type_vocab_size: int = 1,
    torchscript: bool = False,
    mixed_precision: bool = False,
    grad_scaler_config: dict = SimpleFrozenDict(),
    wrapped_listener: Optional[TransformerListenerModelT] = None,
) -> Union[TransformerModelT, WrappedTransformerAndListenerModelT]:
    """Construct a XLM-RoBERTa transformer model.

    vocab_size (int):
        Vocabulary size.
    with_spans (Callable):
        Callback that constructs a span generator model.
    piece_encoder (Model)
        The piece encoder to segment input tokens.
    attention_probs_dropout_prob (float):
        Dropout probabilty of the self-attention layers.
    hidden_act (str):
        Activation used by the point-wise feed-forward layers.
    hidden_dropout_prob (float):
        Dropout probabilty of the point-wise feed-forward and
        embedding layers.
    hidden_width (int):
        Width of the final representations.
    intermediate_width (int):
        Width of the intermediate projection layer in the
        point-wise feed-forward layer.
    layer_norm_eps (float):
        Epsilon for layer normalization.
    max_position_embeddings (int):
        Maximum length of position embeddings.
    model_max_length (int):
        Maximum length of model inputs.
    num_attention_heads (int):
        Number of self-attention heads.
    num_hidden_layers (int):
        Number of hidden layers.
    padding_idx (int):
        Index of the padding meta-token.
    type_vocab_size (int):
        Type vocabulary size.
    torchscript (bool):
        Set to `True` when loading TorchScript models, `False` otherwise.
    mixed_precision (bool):
        Use mixed-precision training.
    grad_scaler_config (dict):
        Configuration passed to the PyTorch gradient scaler.
    wrapped_listener (Optional[TransformerListenerModelT]):
        Optional listener to wrap. Only used when replacing listeners
        in downstream components.
    """
    config = RobertaConfig(
        embedding_width=hidden_width,
        hidden_width=hidden_width,
        intermediate_width=intermediate_width,
        num_attention_heads=num_attention_heads,
        num_hidden_layers=num_hidden_layers,
        attention_probs_dropout_prob=attention_probs_dropout_prob,
        hidden_dropout_prob=hidden_dropout_prob,
        hidden_act=hidden_act,
        vocab_size=vocab_size,
        type_vocab_size=type_vocab_size,
        max_position_embeddings=max_position_embeddings,
        model_max_length=model_max_length,
        layer_norm_eps=layer_norm_eps,
        padding_idx=padding_idx,
    )

    if torchscript:
        transformer = _torchscript_encoder(
            model_max_length=model_max_length, padding_idx=padding_idx
        )
    else:
        encoder = RobertaEncoder(config)
        transformer = _pytorch_encoder(
            encoder,
            hidden_width=hidden_width,
            mixed_precision=mixed_precision,
            grad_scaler_config=grad_scaler_config,
        )

    return build_transformer_or_listener_wrapper_v1(
        with_spans=with_spans,
        piece_encoder=piece_encoder,
        transformer=transformer,
        wrapped_listener=wrapped_listener,
    )


def build_transformer_or_listener_wrapper_v1(
    *,
    with_spans: Callable[
        [TorchTransformerModelT],
        SpanExtractorModelT,
    ],
    transformer: TorchTransformerModelT,
    piece_encoder: Tok2PiecesModelT,
    wrapped_listener: Optional[TransformerListenerModelT],
) -> Union[TransformerModelT, WrappedTransformerAndListenerModelT]:
    thinc_transformer = build_transformer_model_v1(
        with_spans=with_spans, transformer=transformer, piece_encoder=piece_encoder
    )
    if wrapped_listener is not None:
        return WrappedTransformerAndListener(thinc_transformer, wrapped_listener)
    else:
        return thinc_transformer


def build_transformer_model_v1(
    *,
    with_spans: Callable[
        [TorchTransformerModelT],
        SpanExtractorModelT,
    ],
    transformer: TorchTransformerModelT,
    piece_encoder: Tok2PiecesModelT,
) -> TransformerModelT:
    # FIXME: do we want to make `remove_bos_eos` configurable as well or
    #        is it always the same post-processing?
    layers = [
        with_non_ws_tokens(
            chain(piece_encoder, with_spans(transformer), remove_bos_eos())
        )
    ]
    refs = {
        "piece_encoder": piece_encoder,
        "transformer": transformer,
    }
    return Model(
        "transformer_model",
        transformer_model_forward,
        init=transformer_model_init,
        layers=layers,
        refs=refs,  # type: ignore
        attrs={
            "replace_listener": replace_listener_callback,
            "replace_listener_cfg": replace_listener_cfg_callback,
        },
        dims={"nO": transformer.get_dim("nO")},
    )


def transformer_model_forward(
    model: TransformerModelT, docs: TransformerInT, is_train: bool
) -> Tuple[TransformerOutT, TransformerBackpropT]:
    Y, backprop_layer = model.layers[0](docs, is_train=is_train)

    def backprop(dY):
        backprop_layer(dY)

        # Return empty list for backprop, since we cannot backprop into piece
        # identifiers.
        return []

    return Y, backprop


def transformer_model_init(
    model: TransformerModelT, X: Optional[TransformerInT] = None, Y=None
) -> Model:
    model.layers[0].initialize(X, Y)
    return model


def _pytorch_encoder(
    encoder: CuratedEncoderT,
    hidden_width: int,
    *,
    mixed_precision: bool = False,
    grad_scaler_config: dict = SimpleFrozenDict(),
) -> TorchTransformerModelT:
    if isinstance(grad_scaler_config, SimpleFrozenDict):
        # Create a new, mutable dict instance.
        grad_scaler_config = {}

    if "enabled" not in grad_scaler_config:
        grad_scaler_config["enabled"] = mixed_precision

    model = PyTorchWrapper_v2(
        CuratedTransformer(encoder),
        convert_inputs=partial(
            _convert_inputs,
            max_model_seq_len=encoder.max_seq_len,
            padding_idx=encoder.padding_idx,
        ),
        convert_outputs=_convert_outputs,
        mixed_precision=mixed_precision,
        grad_scaler=PyTorchGradScaler(**grad_scaler_config),
    )
    model.set_dim("nO", hidden_width)

    # This attribute is set by the parent Pipe instance before each forward pass.
    model.attrs["_all_layer_outputs"] = True

    return model


def _torchscript_encoder(*, model_max_length: int, padding_idx: int) -> Model:
    return TorchScriptWrapper_v1(
        convert_inputs=partial(
            _convert_inputs,
            max_model_seq_len=model_max_length,
            padding_idx=padding_idx,
        ),
        convert_outputs=_convert_outputs,
    )


def _convert_inputs(
    model: Model,
    X: TorchTransformerInT,
    is_train: bool,
    *,
    max_model_seq_len: int,
    padding_idx: int,
) -> Tuple[ArgsKwargs, Callable[[Any], List[Ints1d]]]:
    ops = model.ops
    max_seq_len = max(x.size for x in X)
    if max_seq_len > max_model_seq_len:
        raise ValueError(
            "At least one sequence in the transformer's input has a length "
            f"of {max_seq_len}, which is larger than the model's maximum sequence "
            f"length of {max_model_seq_len} tokens"
        )

    # Transform the list of strided spans to a padded array.
    Xt = ops.xp.full((len(X), max_seq_len), padding_idx)
    for i in range(len(X)):
        span = X[i]
        span_len = span.shape[0]
        Xt[i, :span_len] = span
    if ops.device_type == 'gpu':
        device = torch.device(f"cuda:{ops.device_id}")
        Xt = xp2torch(Xt, device=device)
    else:
        Xt = xp2torch(Xt)

    def convert_from_torch_backward(d_inputs: Any):
        # No gradients for the inputs.
        return [ops.alloc1f(x.shape[0]) for x in X]

    output = ArgsKwargs(args=(Xt,), kwargs={})
    return output, convert_from_torch_backward


def _convert_outputs(
    model: Model,
    inputs_outputs: Tuple[TorchTransformerInT, PyTorchTransformerOutput],
    is_train: bool,
) -> Tuple[TorchTransformerOutT, Callable[[List[List[Floats2d]]], ArgsKwargs]]:
    model_inputs, model_outputs = inputs_outputs
    ops = model.ops
    all_layer_outputs: bool = model.attrs["_all_layer_outputs"]

    # Strip the outputs for the padding timesteps
    # while preserving all the outputs (and their order).
    input_lens = [x.shape[0] for x in model_inputs]
    if all_layer_outputs:
        Yt = [
            [output[i, :len, :] for output in model_outputs.all_outputs]
            for i, len in enumerate(input_lens)
        ]
    else:
        Yt = [
            [model_outputs.all_outputs[-1][i, :len, :]]
            for i, len in enumerate(input_lens)
        ]

    Y = [
        [cast(Floats2d, torch2xp(layer, ops=ops)) for layer in output] for output in Yt
    ]
    output = TransformerModelOutput(outputs=Y, last_layer_only=not all_layer_outputs)

    def convert_for_torch_backward(dY: List[List[Floats2d]]):
        Yt_flat = [y for inner in Yt for y in inner]
        dYt_flat = [xp2torch(y) for inner in dY for y in inner]
        assert len(Yt_flat) == len(dYt_flat)

        return ArgsKwargs(
            args=(Yt_flat,),
            kwargs={"grad_tensors": dYt_flat},
        )

    return output, convert_for_torch_backward


def build_pytorch_checkpoint_loader_v1(
    *, path: Path
) -> Callable[
    [TorchTransformerModelT, Optional[List[Doc]], Optional[List[Doc]]],
    TorchTransformerModelT,
]:
    """Construct a callback that initializes a supported transformer
    model with weights from a PyTorch checkpoint.

    path (Path):
        Path to the PyTorch checkpoint.
    """

    def load(model, X=None, Y=None):
        encoder = model.shims[0]._model
        device = get_torch_default_device()
        params = torch.load(path, map_location=device)
        params = convert_pretrained_model_for_encoder(encoder, params)
        encoder.load_state_dict(params)
        encoder.to(device)
        return model

    return load
