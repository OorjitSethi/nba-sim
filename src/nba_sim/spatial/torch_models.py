"""Optional trainable tracking architectures.

The module imports without PyTorch installed. Instantiating a neural model gives a
clear dependency error; the deterministic simulation engine remains usable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

try:
    import torch
    from torch import nn
    from torch.nn import functional as functional
except ImportError:  # pragma: no cover - exercised in the default lightweight env
    torch = None
    nn = None
    functional = None


def torch_available() -> bool:
    return torch is not None


def _missing_torch() -> ImportError:
    return ImportError(
        "PyTorch is required for learned tracking models. "
        "Install the project with the 'tracking' extra."
    )


@dataclass(frozen=True)
class CourtMotionConfig:
    joints: int = 29
    pose_hidden_dim: int = 64
    model_dim: int = 512
    transformer_layers: int = 6
    attention_heads: int = 8
    skeleton_graph_layers: int = 5
    skeleton_hz: int = 30
    model_hz: int = 5
    trajectory_bins_per_axis: int = 11
    event_classes: int = 9
    dropout: float = 0.1

    def __post_init__(self) -> None:
        if self.skeleton_hz % self.model_hz:
            raise ValueError("skeleton_hz must be divisible by model_hz")
        if self.model_dim % self.attention_heads:
            raise ValueError("model_dim must be divisible by attention_heads")

    @property
    def temporal_stride(self) -> int:
        return self.skeleton_hz // self.model_hz

    @property
    def trajectory_classes(self) -> int:
        return self.trajectory_bins_per_axis**2


@dataclass(frozen=True)
class SportsNGENConfig:
    object_feature_dim: int = 13
    context_dim: int = 16
    identity_vocab_size: int = 1024
    identity_dim: int = 32
    model_dim: int = 256
    transformer_layers: int = 6
    attention_heads: int = 8
    offset_bins_per_axis: int = 31
    dropout: float = 0.1

    def __post_init__(self) -> None:
        if self.model_dim % self.attention_heads:
            raise ValueError("model_dim must be divisible by attention_heads")
        if self.offset_bins_per_axis < 3 or self.offset_bins_per_axis % 2 == 0:
            raise ValueError("offset bins must be an odd integer >= 3")


if nn is not None:

    def _time_causal_mask(
        timesteps: int,
        agents: int,
        *,
        device: "torch.device",
    ) -> "torch.Tensor":
        """Allow every object to see all objects at its time and earlier times."""

        token_times = torch.arange(timesteps, device=device).repeat_interleave(agents)
        query_times = token_times[:, None]
        key_times = token_times[None, :]
        return key_times > query_times


    class DirectedSkeletonBlock(nn.Module):
        """Directed joint/edge message passing in the spirit of CourtMotion."""

        def __init__(self, hidden_dim: int) -> None:
            super().__init__()
            self.edge_update = nn.Sequential(
                nn.Linear(hidden_dim * 3, hidden_dim),
                nn.GELU(),
                nn.Linear(hidden_dim, hidden_dim),
            )
            self.vertex_update = nn.Sequential(
                nn.Linear(hidden_dim * 3, hidden_dim),
                nn.GELU(),
                nn.Linear(hidden_dim, hidden_dim),
            )
            self.normalization = nn.LayerNorm(hidden_dim)

        def forward(
            self,
            vertices: "torch.Tensor",
            edges: "torch.Tensor",
        ) -> "torch.Tensor":
            # vertices: [batch, time, players, joints, hidden]
            parents = edges[:, 0]
            children = edges[:, 1]
            parent_state = vertices.index_select(-2, parents)
            child_state = vertices.index_select(-2, children)
            edge_state = self.edge_update(
                torch.cat(
                    [parent_state, child_state, parent_state - child_state],
                    dim=-1,
                )
            )

            incoming = torch.zeros_like(vertices)
            outgoing = torch.zeros_like(vertices)
            incoming.index_add_(-2, children, edge_state)
            outgoing.index_add_(-2, parents, edge_state)

            incoming_counts = torch.bincount(
                children,
                minlength=vertices.shape[-2],
            ).clamp_min(1)
            outgoing_counts = torch.bincount(
                parents,
                minlength=vertices.shape[-2],
            ).clamp_min(1)
            shape = (1,) * (vertices.ndim - 2) + (vertices.shape[-2], 1)
            incoming = incoming / incoming_counts.reshape(shape)
            outgoing = outgoing / outgoing_counts.reshape(shape)
            update = self.vertex_update(
                torch.cat([vertices, incoming, outgoing], dim=-1)
            )
            return self.normalization(vertices + update)


    class SkeletonGraphEncoder(nn.Module):
        """Compress 30 Hz 3D skeletons into 5 Hz player pose embeddings."""

        def __init__(
            self,
            config: CourtMotionConfig,
            skeleton_edges: Sequence[tuple[int, int]],
        ) -> None:
            super().__init__()
            if not skeleton_edges:
                raise ValueError("skeleton topology cannot be empty")
            edge_tensor = torch.as_tensor(skeleton_edges, dtype=torch.long)
            if edge_tensor.ndim != 2 or edge_tensor.shape[1] != 2:
                raise ValueError("skeleton edges must have shape (edges, 2)")
            if int(edge_tensor.max()) >= config.joints or int(edge_tensor.min()) < 0:
                raise ValueError("skeleton edge references an invalid joint")
            self.config = config
            self.register_buffer("skeleton_edges", edge_tensor, persistent=True)
            self.joint_projection = nn.Linear(3, config.pose_hidden_dim)
            self.blocks = nn.ModuleList(
                DirectedSkeletonBlock(config.pose_hidden_dim)
                for _ in range(config.skeleton_graph_layers)
            )
            self.temporal = nn.Conv1d(
                config.pose_hidden_dim,
                config.pose_hidden_dim,
                kernel_size=config.temporal_stride,
                stride=config.temporal_stride,
            )
            self.output_normalization = nn.LayerNorm(config.pose_hidden_dim)

        def forward(self, skeletons: "torch.Tensor") -> "torch.Tensor":
            if skeletons.ndim != 5 or skeletons.shape[-1] != 3:
                raise ValueError(
                    "skeletons must have shape [batch, time, players, joints, 3]"
                )
            if skeletons.shape[-2] != self.config.joints:
                raise ValueError("skeleton joint count does not match configuration")
            if skeletons.shape[1] < self.config.temporal_stride:
                raise ValueError("skeleton sequence is too short to downsample")

            state = self.joint_projection(skeletons)
            for block in self.blocks:
                state = block(state, self.skeleton_edges)
            state = state.mean(dim=-2)  # joint pooling

            batch, timesteps, players, hidden = state.shape
            temporal_input = (
                state.permute(0, 2, 3, 1)
                .contiguous()
                .reshape(batch * players, hidden, timesteps)
            )
            encoded = self.temporal(temporal_input)
            output_steps = encoded.shape[-1]
            encoded = (
                encoded.reshape(batch, players, hidden, output_steps)
                .permute(0, 3, 1, 2)
                .contiguous()
            )
            return self.output_normalization(encoded)


    class CourtMotionModel(nn.Module):
        """Basketball skeletal GNN + temporal interaction transformer."""

        def __init__(
            self,
            config: CourtMotionConfig,
            skeleton_edges: Sequence[tuple[int, int]],
        ) -> None:
            super().__init__()
            self.config = config
            self.skeleton_encoder = SkeletonGraphEncoder(config, skeleton_edges)
            input_dim = config.pose_hidden_dim + 2 + 2
            self.state_projection = nn.Linear(input_dim, config.model_dim)
            layer = nn.TransformerEncoderLayer(
                d_model=config.model_dim,
                nhead=config.attention_heads,
                dim_feedforward=config.model_dim * 4,
                dropout=config.dropout,
                activation="gelu",
                batch_first=True,
                norm_first=True,
            )
            self.transformer = nn.TransformerEncoder(
                layer,
                num_layers=config.transformer_layers,
                norm=nn.LayerNorm(config.model_dim),
            )
            self.trajectory_head = nn.Linear(
                config.model_dim,
                config.trajectory_classes,
            )
            self.event_projection = nn.Linear(
                config.model_dim,
                3 * config.event_classes,
            )

        def forward(
            self,
            *,
            skeletons_30hz: "torch.Tensor",
            positions_5hz: "torch.Tensor",
            shoulder_normals_5hz: "torch.Tensor",
        ) -> dict[str, "torch.Tensor"]:
            pose = self.skeleton_encoder(skeletons_30hz)
            if positions_5hz.shape[:-1] != pose.shape[:-1]:
                raise ValueError("position timestamps do not align with pose embeddings")
            if shoulder_normals_5hz.shape != positions_5hz.shape:
                raise ValueError("shoulder normals must align with 2D positions")

            state = torch.cat(
                [pose, shoulder_normals_5hz, positions_5hz],
                dim=-1,
            )
            state = self.state_projection(state)
            batch, timesteps, players, hidden = state.shape
            tokens = state.reshape(batch, timesteps * players, hidden)
            mask = _time_causal_mask(
                timesteps,
                players,
                device=tokens.device,
            )
            embedding = self.transformer(tokens, mask=mask)
            embedding = embedding.reshape(batch, timesteps, players, hidden)
            predictive_embedding = embedding[:, :-1]
            trajectory_logits = self.trajectory_head(predictive_embedding)
            event_logits = self.event_projection(predictive_embedding).reshape(
                batch,
                timesteps - 1,
                players,
                3,
                self.config.event_classes,
            )
            return {
                "embedding": embedding,
                "trajectory_logits": trajectory_logits,
                "event_logits": event_logits,
            }

        def multitask_loss(
            self,
            output: dict[str, "torch.Tensor"],
            *,
            trajectory_targets: "torch.Tensor",
            event_targets: "torch.Tensor",
            trajectory_weight: float = 0.5,
        ) -> dict[str, "torch.Tensor"]:
            if not 0.0 <= trajectory_weight <= 1.0:
                raise ValueError("trajectory_weight must be in [0, 1]")
            trajectory_loss = functional.cross_entropy(
                output["trajectory_logits"].flatten(0, -2),
                trajectory_targets.flatten(),
            )
            event_loss = functional.binary_cross_entropy_with_logits(
                output["event_logits"],
                event_targets.to(output["event_logits"].dtype),
            )
            total = (
                trajectory_weight * trajectory_loss
                + (1.0 - trajectory_weight) * event_loss
            )
            return {
                "loss": total,
                "trajectory_loss": trajectory_loss,
                "event_loss": event_loss,
            }


    class SportsNGENModel(nn.Module):
        """Autoregressive multi-agent decoder with bounded offset classes.

        Axis-factorized offset heads keep basketball-scale training tractable while
        retaining SportsNGEN's classification-and-sampling formulation.
        """

        def __init__(self, config: SportsNGENConfig) -> None:
            super().__init__()
            self.config = config
            self.identity_embedding = nn.Embedding(
                config.identity_vocab_size,
                config.identity_dim,
            )
            self.context_projection = nn.Linear(config.context_dim, config.model_dim)
            self.object_projection = nn.Linear(
                config.object_feature_dim + config.identity_dim,
                config.model_dim,
            )
            layer = nn.TransformerEncoderLayer(
                d_model=config.model_dim,
                nhead=config.attention_heads,
                dim_feedforward=config.model_dim * 4,
                dropout=config.dropout,
                activation="gelu",
                batch_first=True,
                norm_first=True,
            )
            self.decoder = nn.TransformerEncoder(
                layer,
                num_layers=config.transformer_layers,
                norm=nn.LayerNorm(config.model_dim),
            )
            self.offset_head = nn.Linear(
                config.model_dim,
                3 * config.offset_bins_per_axis,
            )
            self.event_head = nn.Linear(config.model_dim, 9)

        def forward(
            self,
            *,
            object_features: "torch.Tensor",
            identity_indices: "torch.Tensor",
            context_features: "torch.Tensor",
        ) -> dict[str, "torch.Tensor"]:
            if object_features.ndim != 4:
                raise ValueError(
                    "object_features must have shape [batch, time, agents, features]"
                )
            batch, timesteps, agents, feature_dim = object_features.shape
            if feature_dim != self.config.object_feature_dim:
                raise ValueError("object feature dimension does not match configuration")
            if identity_indices.shape != (batch, agents):
                raise ValueError("identity indices must have shape [batch, agents]")
            if context_features.shape != (batch, self.config.context_dim):
                raise ValueError("context features do not match configuration")

            identities = self.identity_embedding(identity_indices)
            identities = identities[:, None, :, :].expand(
                batch,
                timesteps,
                agents,
                self.config.identity_dim,
            )
            tokens = self.object_projection(
                torch.cat([object_features, identities], dim=-1)
            )
            context = self.context_projection(context_features)[:, None, None, :]
            tokens = tokens + context
            tokens = tokens.reshape(batch, timesteps * agents, self.config.model_dim)
            mask = _time_causal_mask(
                timesteps,
                agents,
                device=tokens.device,
            )
            embedding = self.decoder(tokens, mask=mask)
            embedding = embedding.reshape(
                batch,
                timesteps,
                agents,
                self.config.model_dim,
            )
            offset_logits = self.offset_head(embedding).reshape(
                batch,
                timesteps,
                agents,
                3,
                self.config.offset_bins_per_axis,
            )
            event_logits = self.event_head(embedding)
            return {
                "embedding": embedding,
                "offset_logits": offset_logits,
                "event_logits": event_logits,
            }

else:

    class SkeletonGraphEncoder:
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise _missing_torch()


    class CourtMotionModel:
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise _missing_torch()


    class SportsNGENModel:
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise _missing_torch()


__all__ = [
    "CourtMotionConfig",
    "CourtMotionModel",
    "SkeletonGraphEncoder",
    "SportsNGENConfig",
    "SportsNGENModel",
    "torch_available",
]
