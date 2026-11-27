"""Laeuft in der KI-Umgebung: laedt ein mit LeRobot trainiertes Modell (ACT, SmolVLA, ...) und
berechnet aus Kamerabildern + Gelenkstellung die naechste Aktion. Gleiche Klasse fuer alle LeRobot-Methoden.
Bewegungsstuecke werden im Hintergrund vorausgerechnet (ki/chunks.py), damit der Arm nicht stockt."""
import numpy as np
from .chunks import ChunkScheduler


class LeRobotRunner:
    def __init__(self, checkpoint, device="auto"):
        import torch
        from lerobot.configs import PreTrainedConfig
        from lerobot.policies.factory import get_policy_class, make_pre_post_processors
        self.torch = torch
        from .geraet import resolve
        self.device = torch.device(resolve(device, torch))
        cfg = PreTrainedConfig.from_pretrained(checkpoint)
        cfg.device = self.device.type
        if cfg.type == "act" and hasattr(cfg, "temporal_ensemble_coeff"):
            # Gegen Zittern: jeden Takt neu vorhersagen und die ueberlappenden Vorhersagen gewichtet mitteln
            # (Temporal Ensembling aus dem ACT-Paper; Rechenzeit je Takt nur wenige ms)
            cfg.temporal_ensemble_coeff = 0.01
            cfg.n_action_steps = 1
        self.policy = get_policy_class(cfg.type).from_pretrained(checkpoint, config=cfg)
        self.policy.to(self.device).eval()
        self.pre, self.post = make_pre_post_processors(
            policy_cfg=cfg, pretrained_path=checkpoint,
            preprocessor_overrides={"device_processor": {"device": self.device.type}})
        self.type = cfg.type
        self.image_keys = [k for k in cfg.input_features if k.startswith("observation.images.")]
        self.n_steps = int(getattr(cfg, "n_action_steps", 1) or 1)
        self.chunked = hasattr(self.policy, "predict_action_chunk") and self.n_steps > 1
        self.scheduler = ChunkScheduler(self._compute)
        self.last_compute_ms = None

    def reset(self):
        self.scheduler.reset()
        self.policy.reset()

    def _observation(self, state_deg, images_rgb):
        obs = {"observation.state": np.asarray(state_deg, dtype=np.float32)}
        for key in self.image_keys:
            cam = key.split(".")[-1]
            if cam in images_rgb:
                obs[key] = images_rgb[cam]
        # SmolVLA darf Kameras auslassen (z. B. camera3), die beim Training nicht da waren
        if len(obs) == 1:
            raise KeyError(f"Keine passende Kamera (Modell erwartet {self.image_keys}, bekommen {list(images_rgb)})")
        return obs

    def _compute(self, item):
        """Ein ganzes Bewegungsstueck (Liste von Aktionen in Grad). Laeuft im Hintergrund-Thread."""
        from lerobot.policies.utils import prepare_observation_for_inference
        from lerobot.processor import policy_output_to_transition, transition_to_policy_action
        obs, task = item
        torch = self.torch
        with torch.inference_mode():
            batch = self.pre(prepare_observation_for_inference(dict(obs), self.device, task, "so101_follower"))
            if not self.chunked:
                raw = [self.policy.select_action(batch)]
            else:
                chunk = self.policy.predict_action_chunk(batch)          # (1, n, dim)
                raw = [chunk[:, i] for i in range(min(self.n_steps, chunk.shape[1]))]
            out = []
            for a in raw:
                a = self.post(transition_to_policy_action(policy_output_to_transition(a)))
                out.append(np.asarray(a.detach().float().cpu().numpy() if hasattr(a, "detach") else a,
                                      dtype=np.float32).reshape(-1)[:6])
        return out

    def act(self, state_deg, images_rgb, task):
        """state_deg: 6 Werte in Grad; images_rgb: {kamera: HxWx3 uint8}; -> 6 Werte in Grad."""
        return self.scheduler.next((self._observation(state_deg, images_rgb), task))
