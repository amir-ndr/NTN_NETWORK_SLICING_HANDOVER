"""
Poly-chain NF simulation for NTN 5G network slicing.

Architecture (from the paper):
    Dispatcher → AMF layer (5 instances) → SMF layer (5 instances) → UPF layer (5 instances)

Each slice has 5 NF instances with heterogeneous service rates, modelling realistic
variation in processing capacity and current load. The dispatcher selects one instance
from each layer to form a poly-chain for each handover request.

Instance latencies are drawn from Exponential distributions with different means,
plus a queue backlog term that grows under sustained load (M/M/1 queueing).
"""

import math
import random
import threading

# ── Per-instance mean service times (ms) ─────────────────────────────────────
# Values chosen so instances differ significantly: best ≈ 2–4× faster than worst.
# This creates meaningful CDF separation between random (B2) and Bregman (B3).

AMF_MU_MS = [2.0,  4.0,  8.0, 15.0, 25.0]   # Slice 1: AMF
SMF_MU_MS = [1.0,  3.0,  6.0, 10.0, 18.0]   # Slice 2: SMF
UPF_MU_MS = [0.5,  1.5,  3.0,  6.0, 10.0]   # Slice 3: UPF

N_INSTANCES = 5


class NfInstance:
    """Single NF instance with M/M/1 queue dynamics."""

    def __init__(self, nf_type: str, idx: int, mu_ms: float):
        self.nf_type  = nf_type
        self.idx      = idx
        self.mu_ms    = mu_ms        # mean service time (ms)
        self._lock    = threading.Lock()
        self._backlog = 0.0          # estimated tasks in queue

    def process(self) -> float:
        """Simulate one task. Returns total delay in ms (service + queueing)."""
        with self._lock:
            service_ms   = random.expovariate(1.0 / self.mu_ms)
            queue_delay  = self._backlog * self.mu_ms * 0.15   # proportional to queue depth
            # Lindley recursion: queue decreases by one served task, increases by new arrival
            self._backlog = max(0.0, self._backlog - 1.0) + 0.12
            return service_ms + queue_delay

    @property
    def backlog(self) -> float:
        """Current queue backlog depth (thread-safe read)."""
        with self._lock:
            return self._backlog

    @property
    def cost(self) -> float:
        """Estimated cost L(·) for Bregman algorithm: mean + queue contribution."""
        return self.mu_ms + self._backlog * self.mu_ms * 0.15


class PolyChain:
    """
    3-layer poly-chain: Dispatcher → AMF (Slice 1) → SMF (Slice 2) → UPF (Slice 3).

    The dispatcher selects one instance from each layer to form the chain.
    Processing is sequential: AMF completes before SMF, SMF before UPF.
    """

    def __init__(self):
        self.amf = [NfInstance('AMF', i, AMF_MU_MS[i]) for i in range(N_INSTANCES)]
        self.smf = [NfInstance('SMF', i, SMF_MU_MS[i]) for i in range(N_INSTANCES)]
        self.upf = [NfInstance('UPF', i, UPF_MU_MS[i]) for i in range(N_INSTANCES)]

    def process_chain(self, amf_idx: int, smf_idx: int, upf_idx: int):
        """
        Process one HO request through the selected chain.
        Returns (total_ms, amf_ms, smf_ms, upf_ms).
        """
        amf_ms = self.amf[amf_idx].process()
        smf_ms = self.smf[smf_idx].process()
        upf_ms = self.upf[upf_idx].process()
        return amf_ms + smf_ms + upf_ms, amf_ms, smf_ms, upf_ms

    # ── Selection policies ────────────────────────────────────────────────────

    def random_select(self):
        """B2: uniform random selection from each layer."""
        return (
            random.randrange(N_INSTANCES),
            random.randrange(N_INSTANCES),
            random.randrange(N_INSTANCES),
        )

    def costs(self):
        """Current cost vector for each layer (used by Bregman algorithm)."""
        return (
            [inst.cost for inst in self.amf],
            [inst.cost for inst in self.smf],
            [inst.cost for inst in self.upf],
        )


class BregmanLayer:
    """
    One level of the poly-chain tree: parent node i selects among N children j.

    Implements Algorithm 1 (exploration part) from the paper using the
    Bregman divergence for the negative-entropy kernel, which yields the
    multiplicative-weight / EXP3 update:

        x_j[t+1] ∝ x_j[t] · exp( −η · cost_hat_j[t] )

    where cost_hat_j = observed_cost / x_j  (importance-weighted, unbiased).

    The per-layer cost is the cost RELAYED from its subtree (Eq. 2):
        L_i[t] = L_i_local[t] + Σ_{j in children} L_j[t]

    so each layer's selection adapts to end-to-end subtree performance,
    not just its immediate child's latency.

    Parameters
    ----------
    n      : number of child instances (N_INSTANCES = 5)
    eta    : learning rate. EXP3 optimal: sqrt(ln(N) / (N·T)).
             For N=5, T=50: ≈ 0.08. Use 0.1 for slightly faster convergence.
    """

    def __init__(self, n: int, eta: float = 0.1):
        self.n   = n
        self.eta = eta
        # Log-space weights for numerical stability (start uniform → all zeros)
        self._log_w = [0.0] * n

    @property
    def x(self) -> list:
        """Softmax selection probabilities (normalised from log-weights)."""
        # Subtract max for numerical stability before exp
        max_lw = max(self._log_w)
        w = [math.exp(lw - max_lw) for lw in self._log_w]
        total = sum(w)
        return [wj / total for wj in w]

    def select(self) -> int:
        """Sample child index proportional to current probabilities."""
        probs = self.x
        r = random.random()
        cumulative = 0.0
        for j, p in enumerate(probs):
            cumulative += p
            if r <= cumulative:
                return j
        return self.n - 1   # numerical safety

    def update(self, j: int, relayed_cost: float) -> None:
        """
        Update weights after selecting child j and observing relayed subtree cost.

        Exploration update (Algorithm 1, Eq. derived from Bregman divergence):
            log w_j[t+1] = log w_j[t] − η · (relayed_cost / x_j[t])

        The division by x_j[t] is importance sampling: it corrects for the fact
        that we only observe cost for the selected child, giving an unbiased
        gradient estimate in expectation (standard EXP3 trick).
        """
        x_j = self.x[j]
        cost_hat = relayed_cost / (x_j + 1e-9)   # importance-weighted gradient
        self._log_w[j] -= self.eta * cost_hat

    def probabilities(self) -> list:
        """Return current selection probabilities (diagnostic)."""
        return self.x


class QueueTracker:
    """
    Discrete-time queue tracker for per-instance load monitoring across HO rounds.

    Unlike NfInstance._backlog (which is a per-call internal latency model),
    this tracker correctly captures cross-round queueing dynamics:

      Every round, for EVERY instance i:
          Q_i[t+1] = Q_i[t] * decay                 # background service (idle drain)

      For the SELECTED instance i* only:
          Q_i*[t+1] += mu_ms[i*] / scale            # new load ∝ service time

    This means:
      - Idle instances drain toward 0 (correctly modelled)
      - Slower instances accumulate MORE backlog per selection (proportional to μ_i)
      - B1 fixed on mid-tier → high backlog on that slow instance
      - B3 converging to fast instance → low backlog across all instances

    Parameters
    ----------
    mu_ms  : list of mean service times per instance (ms)
    decay  : per-round retention factor (0 < decay < 1).
             decay=0.85 → 15% drained per round; reflects inter-HO idle service.
    scale  : load increment divisor. mu_ms[i]/scale added per selection.
             scale=5.0 → mid-tier AMF[2] (8ms) adds 1.6 units/round when always selected
             → steady-state Q = 1.6/(1-0.85) ≈ 10.7  (clearly non-zero, comparable to μ)
    """

    def __init__(self, mu_ms: list, decay: float = 0.85, scale: float = 5.0):
        self.mu_ms = list(mu_ms)
        self.decay = decay
        self.scale = scale
        self._q    = [0.0] * len(mu_ms)

    def step(self, selected_idx: int) -> None:
        """One HO round: drain all instances, add load to the selected one."""
        self._q = [qi * self.decay for qi in self._q]
        self._q[selected_idx] += self.mu_ms[selected_idx] / self.scale

    def state(self) -> list:
        """Current queue depth for all instances (copy)."""
        return list(self._q)


class BregmanPolyChain:
    """
    Hierarchical Bregman online selector across 3 layers.

    Tree structure (from paper):
        Dispatcher → AMF layer (Slice 1, 5 instances)
                   → SMF layer (Slice 2, 5 instances)
                   → UPF layer (Slice 3, 5 instances)

    Cost relay (Eq. 2):
        L_UPF[t]  = observed UPF latency
        L_SMF[t]  = observed SMF latency + L_UPF[t]   (relay from UPF)
        L_AMF[t]  = observed AMF latency + L_SMF[t]   (relay from SMF)
        (Dispatcher uses L_AMF as its total feedback)

    Each layer's BregmanLayer updates its weights based on the cost relayed
    from its subtree, so the dispatcher learns which AMF leads to the best
    end-to-end chain, not just which AMF is fastest on its own.
    """

    def __init__(self, chain: PolyChain, eta: float = 0.1):
        self.chain = chain
        # One BregmanLayer per tree level
        self.smf_selector  = BregmanLayer(N_INSTANCES, eta)   # SMF selects UPF
        self.amf_selector  = BregmanLayer(N_INSTANCES, eta)   # AMF selects SMF
        self.disp_selector = BregmanLayer(N_INSTANCES, eta)   # Dispatcher selects AMF

    def select_and_process(self):
        """
        Select chain via Bregman, process request, relay costs, update weights.
        Returns (total_ms, amf_ms, smf_ms, upf_ms, amf_idx, smf_idx, upf_idx).
        """
        # ── Forward pass: select at each level ───────────────────────────────
        amf_idx = self.disp_selector.select()
        smf_idx = self.amf_selector.select()
        upf_idx = self.smf_selector.select()

        # ── Process through selected chain ────────────────────────────────────
        amf_ms = self.chain.amf[amf_idx].process()
        smf_ms = self.chain.smf[smf_idx].process()
        upf_ms = self.chain.upf[upf_idx].process()

        # ── Cost relay: bottom-up (Eq. 2) ────────────────────────────────────
        L_upf = upf_ms
        L_smf = smf_ms + L_upf     # SMF cost + UPF relay
        L_amf = amf_ms + L_smf     # AMF cost + SMF relay (= total chain)

        # ── Backward pass: update each layer's weights ────────────────────────
        # SMF-level selector learns which UPF is best (cost = UPF latency)
        self.smf_selector.update(upf_idx, L_upf)
        # AMF-level selector learns which SMF leads to best SMF+UPF subtree
        self.amf_selector.update(smf_idx, L_smf)
        # Dispatcher learns which AMF leads to best full chain
        self.disp_selector.update(amf_idx, L_amf)

        total_ms = amf_ms + smf_ms + upf_ms
        return total_ms, amf_ms, smf_ms, upf_ms, amf_idx, smf_idx, upf_idx
