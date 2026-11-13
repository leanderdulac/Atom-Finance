# /// script
# requires-python = ">=3.10"
# dependencies = ["numpy", "scipy", "matplotlib", "pillow"]
# ///
"""
Mesma correlação, cauda conjunta diferente
==========================================
Gera o GIF "cópula Normal vs cópula t" com a correlação de Pearson travada.

Para cada quadro, o grau de liberdade ν da cópula t cai (cauda mais pesada) e o
parâmetro ρ da cópula é RECALIBRADO para que a correlação de Pearson dos
retornos padronizados (margens N(0,1)) continue exatamente no alvo (0,29).
Assim, a única coisa que muda é a dependência de cauda.

Métrica exibida (finita, não assintótica):
    χ(q) = P(U_B ≤ q | U_A ≤ q)   — "dado um dos piores q% dias de A,
                                     chance de B também estar no pior q%"

Uso:
    uv run scripts/tail_dependence_gif.py                 # gera tail_dependence.gif
    uv run scripts/tail_dependence_gif.py --check         # só imprime a tabela
    uv run scripts/tail_dependence_gif.py --nu-min 3 --target-r 0.29 --q 0.05 --out x.gif
"""

from __future__ import annotations

import argparse

import numpy as np
from scipy import stats
from scipy.optimize import brentq

# ── Simulação com números aleatórios comuns ──────────────────────────────────
# Usamos os MESMOS Z1, Z2 e V em todos os quadros. O mixing χ²_ν é obtido por
# quantil (chi2.ppf(V, ν)), então os pontos se movem continuamente quando ν
# muda: a animação fica suave e a comparação entre quadros não tem ruído.


class CommonDraws:
    def __init__(self, n: int, seed: int = 2008):
        rng = np.random.default_rng(seed)
        self.z1 = rng.standard_normal(n)
        self.z2 = rng.standard_normal(n)
        self.v = rng.uniform(1e-12, 1 - 1e-12, n)

    def uniforms(self, rho: float, nu: float, sl: slice = slice(None)) -> tuple[np.ndarray, np.ndarray]:
        """Pseudo-observações (U_A, U_B) da cópula t(ρ, ν); ν=inf → cópula Normal."""
        z1, z2 = self.z1[sl], self.z2[sl]
        x1 = z1
        x2 = rho * z1 + np.sqrt(1.0 - rho**2) * z2
        if np.isinf(nu):
            return stats.norm.cdf(x1), stats.norm.cdf(x2)
        s = np.sqrt(stats.chi2.ppf(self.v[sl], nu) / nu)
        return stats.t.cdf(x1 / s, nu), stats.t.cdf(x2 / s, nu)

    def normal_scores(self, rho: float, nu: float, sl: slice = slice(None)) -> tuple[np.ndarray, np.ndarray]:
        """Retornos padronizados: cópula t + margens N(0,1)."""
        u1, u2 = self.uniforms(rho, nu, sl)
        eps = 1e-12
        return (stats.norm.ppf(np.clip(u1, eps, 1 - eps)),
                stats.norm.ppf(np.clip(u2, eps, 1 - eps)))


def pearson(draws: CommonDraws, rho: float, nu: float) -> float:
    a, b = draws.normal_scores(rho, nu)
    return float(np.corrcoef(a, b)[0, 1])


def calibrate_rho(draws: CommonDraws, nu: float, target_r: float) -> float:
    """ρ da cópula que produz Pearson = target_r nos retornos padronizados."""
    return float(brentq(lambda r: pearson(draws, r, nu) - target_r, -0.95, 0.95, xtol=1e-5))


def chi_q(draws: CommonDraws, rho: float, nu: float, q: float) -> float:
    u1, u2 = draws.uniforms(rho, nu)
    return float(np.mean((u1 <= q) & (u2 <= q)) / q)


def chi_q_gaussian_exact(rho: float, q: float) -> float:
    k = stats.norm.ppf(q)
    joint = stats.multivariate_normal(mean=[0, 0], cov=[[1, rho], [rho, 1]]).cdf([k, k])
    return float(joint / q)


def lambda_t(rho: float, nu: float) -> float:
    """Dependência de cauda assintótica da cópula t (λ_L = λ_U)."""
    if np.isinf(nu):
        return 0.0
    return float(2 * stats.t.cdf(-np.sqrt((nu + 1) * (1 - rho) / (1 + rho)), nu + 1))


def br(x: float, nd: int = 2) -> str:
    """Formato numérico pt-BR (vírgula decimal)."""
    return f"{x:.{nd}f}".replace(".", ",")


# ── Pipeline ─────────────────────────────────────────────────────────────────

def build_frames(draws: CommonDraws, nus: list[float], target_r: float, q: float) -> list[dict]:
    frames = []
    for nu in nus:
        rho = calibrate_rho(draws, nu, target_r)
        frames.append({
            "nu": nu,
            "rho": rho,
            "r": pearson(draws, rho, nu),
            "chi": chi_q(draws, rho, nu, q),
            "lam": lambda_t(rho, nu),
        })
    return frames


def print_table(frames: list[dict], chi_gauss: float, q: float) -> None:
    print(f"\nq = {q:.0%} | independência: χ = {q:.1%} | cópula Normal (exato): χ = {chi_gauss:.1%}\n")
    print(f"{'ν':>8} {'ρ cópula':>10} {'Pearson r':>10} {'χ(q)':>8} {'λ assint.':>10}")
    for f in frames:
        nu = "∞" if np.isinf(f["nu"]) else f"{f['nu']:.1f}"
        print(f"{nu:>8} {f['rho']:>10.4f} {f['r']:>10.4f} {f['chi']:>8.1%} {f['lam']:>10.3f}")


def render_gif(draws: CommonDraws, frames: list[dict], chi_gauss: float, q: float,
               target_r: float, n_plot: int, out: str, fps: int) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation, PillowWriter

    BG, INK, MUTED = "#f7f8fa", "#1f2328", "#57606a"
    RED, BLUE, GREY = "#e5482b", "#2f7de1", "#8b95a5"

    plt.rcParams.update({"font.family": "DejaVu Sans", "axes.edgecolor": "#d0d7de"})
    fig = plt.figure(figsize=(10.24, 8.2), dpi=100, facecolor=BG)
    ax = fig.add_axes((0.10, 0.08, 0.50, 0.50), facecolor=BG)
    axb = fig.add_axes((0.70, 0.08, 0.26, 0.50), facecolor=BG)

    k = stats.norm.ppf(q)
    sl = slice(0, n_plot)

    fig.text(0.04, 0.95, "Mesma correlação. Cauda conjunta diferente.",
             fontsize=20, weight="bold", color=INK)
    fig.text(0.10, 0.895, f"Correlação linear (Pearson): r = {br(target_r)}  —  não se mexe",
             fontsize=14, color=INK)
    fig.text(0.10, 0.85, f"Se o ativo A tem um dos {q:.0%} piores dias, chance de B afundar junto:",
             fontsize=12.5, color=INK)
    big = fig.text(0.10, 0.765, "", fontsize=38, weight="bold", color=RED)
    sub = fig.text(0.10, 0.665, "", fontsize=12, color=MUTED, linespacing=1.5)

    # Scatter
    ax.axvspan(-6, k, ymin=0, ymax=(k + 6) / 12, color=RED, alpha=0.06, lw=0)
    ax.axhline(0, color="#d0d7de", lw=0.8)
    ax.axvline(0, color="#d0d7de", lw=0.8)
    ax.axvline(k, color=BLUE, ls="--", lw=1.4)
    ax.axhline(k, color=BLUE, ls="--", lw=1.4, label=f"corte do pior {q:.0%}\nde cada ativo")
    calm = ax.scatter([], [], s=4, color=GREY, alpha=0.35, lw=0, label="dias comuns")
    crash = ax.scatter([], [], s=14, color=RED, lw=0,
                       label=f"co-quedas\n(A e B no pior {q:.0%})")
    ax.set(xlim=(-6, 6), ylim=(-6, 6))
    ax.set_xlabel("Retorno padronizado — Ativo A (σ)", fontsize=12, color=INK)
    ax.set_ylabel("Retorno padronizado — Ativo B (σ)", fontsize=12, color=INK)
    ax.grid(alpha=0.25)
    ax.legend(loc="upper left", fontsize=9, frameon=True, facecolor="white", markerscale=1.5)

    # Barras de referência
    labels = ["Indepen-\ndência", "Cópula\nNormal", "Cauda\npesada"]
    bars = axb.bar(labels, [q, chi_gauss, chi_gauss], color=["#c9d1d9", GREY, RED], width=0.65)
    axb.axhline(chi_gauss, color=GREY, ls=":", lw=1.2)
    ymax = max(f["chi"] for f in frames) * 1.25
    axb.set_ylim(0, ymax)
    axb.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    axb.tick_params(axis="x", labelsize=9, colors=INK)
    axb.spines[["top", "right"]].set_visible(False)
    axb.set_title(f"P(B no pior {q:.0%} | A no pior {q:.0%})", fontsize=10, color=MUTED)
    bar_txt = [axb.text(b.get_x() + b.get_width() / 2, 0, "", ha="center", va="bottom",
                        fontsize=10, weight="bold", color=INK) for b in bars]

    def update(i: int):
        f = frames[i]
        a, b = draws.normal_scores(f["rho"], f["nu"], sl)
        mask = (a <= k) & (b <= k)
        calm.set_offsets(np.column_stack([a[~mask], b[~mask]]))
        crash.set_offsets(np.column_stack([a[mask], b[mask]]))

        big.set_text(f"{f['chi']:.0%}")
        nu_txt = "∞ (cópula Normal)" if np.isinf(f["nu"]) else br(f["nu"], 1)
        sub.set_text(
            f"cauda: graus de liberdade ν = {nu_txt}   (Normal quando ν → ∞)\n"
            f"a cópula Normal com a mesma correlação prevê só ~{chi_gauss:.0%}"
        )
        for bar, txt, val in zip(bars, bar_txt, [q, chi_gauss, f["chi"]]):
            bar.set_height(val)
            txt.set_position((bar.get_x() + bar.get_width() / 2, val + ymax * 0.01))
            txt.set_text(f"{val:.0%}")
        return [calm, crash, big, sub, *bars, *bar_txt]

    anim = FuncAnimation(fig, update, frames=len(frames), blit=False)
    anim.save(out, writer=PillowWriter(fps=fps), savefig_kwargs={"facecolor": BG})
    plt.close(fig)
    print(f"\nGIF salvo em: {out}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--target-r", type=float, default=0.29, help="Pearson alvo (default 0.29)")
    p.add_argument("--q", type=float, default=0.05, help="Quantil de cauda (default 0.05)")
    p.add_argument("--nu-max", type=float, default=200.0)
    p.add_argument("--nu-min", type=float, default=3.0)
    p.add_argument("--steps", type=int, default=30, help="Quadros na transição de ν")
    p.add_argument("--n-sim", type=int, default=500_000, help="Amostra para calibrar ρ e medir χ")
    p.add_argument("--n-plot", type=int, default=4_000, help="Pontos exibidos no scatter")
    p.add_argument("--fps", type=int, default=8)
    p.add_argument("--out", default="tail_dependence.gif")
    p.add_argument("--check", action="store_true", help="Só imprime a tabela, sem GIF")
    args = p.parse_args()

    draws = CommonDraws(args.n_sim)
    transition = list(np.geomspace(args.nu_max, args.nu_min, args.steps))

    rho_gauss = calibrate_rho(draws, np.inf, args.target_r)
    chi_gauss = chi_q_gaussian_exact(rho_gauss, args.q)

    if args.check:
        nus = [np.inf, 30.0, 10.0, 6.0, 4.0, 3.0, 2.5]
        print_table(build_frames(draws, nus, args.target_r, args.q), chi_gauss, args.q)
        return

    # Segura o início (Normal) e o fim (cauda pesada) para leitura.
    nus = [np.inf] * 6 + transition + [args.nu_min] * 12
    frames = build_frames(draws, nus, args.target_r, args.q)
    print_table(frames[5:-11:3], chi_gauss, args.q)
    render_gif(draws, frames, chi_gauss, args.q, args.target_r, args.n_plot, args.out, args.fps)


if __name__ == "__main__":
    main()
