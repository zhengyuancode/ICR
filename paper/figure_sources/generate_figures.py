"""Generate the vector schematics and result summary used by the ISPA paper."""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Polygon, Rectangle
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "figures"
BLUE = "#0072B2"
SKY = "#56B4E9"
GREEN = "#009E73"
ORANGE = "#D55E00"
GRAY = "#59636E"
DARK = "#17212B"
LIGHT_BLUE = "#E8F1F8"
LIGHT_GREEN = "#EAF5F1"


def style():
    plt.rcParams.update({
        "font.family": "DejaVu Sans",
        "font.size": 8.0,
        "axes.titlesize": 8.4,
        "axes.labelsize": 7.6,
        "xtick.labelsize": 7.0,
        "ytick.labelsize": 7.0,
        "legend.fontsize": 7.0,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
        "axes.spines.top": False,
        "axes.spines.right": False,
    })


def box(ax, x, y, w, h, label, edge=GRAY, fill="white", fs=7.5, lw=1.2):
    patch = FancyBboxPatch(
        (x, y), w, h, boxstyle="round,pad=0.025,rounding_size=0.035",
        edgecolor=edge, facecolor=fill, lw=lw,
    )
    ax.add_patch(patch)
    ax.text(x + w / 2, y + h / 2, label, ha="center", va="center",
            fontsize=fs, color=DARK, linespacing=1.12)
    return patch


def arrow(ax, start, end, color=GRAY, ls="-", lw=1.2):
    ax.add_patch(FancyArrowPatch(start, end, arrowstyle="-|>",
                                mutation_scale=9, lw=lw, color=color,
                                linestyle=ls))


def workflow():
    fig, ax = plt.subplots(figsize=(7.10, 3.85))
    ax.set(xlim=(0, 12), ylim=(0, 6.05))
    ax.axis("off")

    # Panel (a): a concrete failure and an invalid single-call substitute.
    ax.text(.05, 5.90, "(a) A local substitute can violate the continuation boundary",
            weight="bold", fontsize=8.5, color=DARK)
    box(ax, .25, 4.55, 1.45, .62, "Observed input\n$a$", GRAY, "white", fs=7.0)
    box(ax, 2.25, 4.55, 2.05, .62, "Replacement for\nproducer $f$", BLUE,
        LIGHT_BLUE, fs=7.0)
    box(ax, 5.05, 4.55, 2.05, .62, "Original consumer\n$c$", ORANGE,
        "#FFF4EC", fs=7.0)
    box(ax, 8.05, 4.55, 2.35, .62, "Unchanged\ncontinuation", GRAY,
        "white", fs=7.0)
    arrow(ax, (1.74, 4.86), (2.21, 4.86), GRAY)
    arrow(ax, (4.34, 4.86), (5.01, 4.86), ORANGE)
    arrow(ax, (7.14, 4.86), (8.01, 4.86), GRAY)
    ax.text(4.68, 5.30, "bridge payload", ha="center", color=ORANGE, fontsize=6.8)
    ax.text(4.68, 4.24, r"$\neg C^{\rho}_{fc}(1,0)$: incompatible ports",
            ha="center", color=ORANGE, fontsize=7.0, weight="bold")
    box(ax, 2.62, 5.31, 1.30, .28, "original $f$ failed", ORANGE, "#FFF4EC",
        fs=6.1, lw=.9)

    # Panel (b): the same call repaired by a minimum interface-closed region.
    ax.text(.05, 3.88, "(b) Closure returns the least interface-closed region",
            weight="bold", fontsize=8.5, color=DARK)
    box(ax, .25, 2.72, 1.20, .56, "immutable\ninput $i$", GRAY, "white", fs=6.8)
    ax.add_patch(Rectangle((1.76, 2.49), 5.44, .93, facecolor=LIGHT_GREEN,
                           edgecolor=GREEN, lw=1.1, ls="--"))
    box(ax, 1.95, 2.68, 1.60, .62, "Replacement for\nproducer $f$", BLUE,
        "white", fs=7.0)
    box(ax, 5.30, 2.68, 1.60, .62, "Replacement for\nconsumer $c$", GREEN,
        "white", fs=7.0)
    box(ax, 7.55, 2.72, 1.20, .56, "immutable\noutput $o$", GRAY, "white", fs=6.8)
    box(ax, 9.15, 2.72, 2.35, .56, "Unchanged\ncontinuation", GRAY,
        "white", fs=6.8)
    arrow(ax, (1.49, 3.00), (1.91, 3.00), GRAY)
    arrow(ax, (3.59, 3.00), (5.26, 3.00), GREEN)
    arrow(ax, (6.94, 3.00), (7.51, 3.00), GREEN)
    arrow(ax, (8.79, 3.00), (9.11, 3.00), GRAY)
    # Center the value annotation in the gap between the two boxes and keep
    # a full text-height of clearance above the connector.
    ax.text(4.425, 3.25, "observed result", ha="center", va="center",
            color=GREEN, fontsize=6.6)
    # Keep the boundary certificate in the annotation band above the dashed
    # repair region; placing it on the boundary makes the subscript collide
    # with the dashed stroke after the figure is reduced in the paper.
    ax.text(7.26, 3.64, r"$C^{\rho}_{co}(1,0)=1$", ha="center", va="center",
            color=GREEN, fontsize=6.4)
    ax.text(1.92, 2.20, r"least region $R^{*}_{\rho}=\{f,c\}$",
            ha="left", color=GREEN, fontsize=7.0, weight="bold")

    # Panel (c): the output packet and the explicit authority branch.
    ax.text(.05, 1.98, "(c) Certification produces evidence; policy controls commitment",
            weight="bold", fontsize=8.5, color=DARK)
    box(ax, .25, .64, 1.70, .86, "Compiled programs\n$\\mathcal{P}(\\xi)$", GRAY,
        "white", fs=7.0)
    box(ax, 2.45, .64, 1.70, .86,
        "Admission filter\n$\\sim_{\\mathrm{op}},\\ K\\ne\\bot,\\ \\Phi=1$", BLUE,
        LIGHT_BLUE, fs=6.6)
    box(ax, 4.65, .46, 2.22, 1.22,
        "Recovery packet\n$p\\in\\mathcal{D}(\\xi)$\ninterface + function\ncontext + effect evidence",
        GREEN, LIGHT_GREEN, fs=6.7)
    diamond = Polygon([[7.48, 1.07], [8.22, 1.62], [8.96, 1.07], [8.22, .52]],
                      closed=True, facecolor="#FFF4EC", edgecolor=ORANGE, lw=1.15)
    ax.add_patch(diamond)
    ax.text(8.22, 1.07, "authority\npolicy", ha="center", va="center",
            fontsize=6.8, color=DARK)
    box(ax, 9.62, 1.22, 2.05, .58, "Advice to model", BLUE, LIGHT_BLUE, fs=6.9)
    box(ax, 9.62, .34, 2.05, .58, "Bind sole path\nand execute", GREEN,
        LIGHT_GREEN, fs=6.7)
    arrow(ax, (1.99, 1.07), (2.41, 1.07), GRAY)
    arrow(ax, (4.19, 1.07), (4.61, 1.07), GRAY)
    arrow(ax, (6.91, 1.07), (7.44, 1.07), GRAY)
    arrow(ax, (8.93, 1.28), (9.58, 1.49), BLUE)
    arrow(ax, (8.93, .86), (9.58, .63), GREEN)
    ax.text(9.20, 1.55, "defer", color=BLUE, fontsize=6.5, ha="center")
    ax.text(9.20, .48, "commit", color=GREEN, fontsize=6.5, ha="center")
    ax.text(5.65, .16,
            "Reject: infeasible interface  |  ineligible function  |  invalid context  |  unproved effect",
            ha="center", color=ORANGE, fontsize=6.2)

    fig.subplots_adjust(left=.02, right=.99, top=.98, bottom=.03)
    fig.savefig(OUT / "continuation_workflow.pdf")
    plt.close(fig)


def obligations():
    fig, ax = plt.subplots(figsize=(3.45, 1.95))
    ax.set(xlim=(-.50, 3.50), ylim=(-1.18, 1.40))
    ax.axis("off")
    ax.text(-.46, 1.24, "Bidirectional closure and feasibility checks",
            weight="bold", fontsize=8.2, color=DARK)
    labels = ["u", "f", "c", "o"]
    roles = ["forced", "failed", "forced", "fixed"]
    for x, label, role in zip(range(4), labels, roles):
        selected = label in {"u", "f", "c"}
        ax.scatter(x, .40, s=430, marker="s" if label == "d" else "o",
                   facecolor=LIGHT_BLUE if selected else "white",
                   edgecolor=BLUE if selected else GRAY, linewidth=1.25, zorder=3)
        ax.text(x, .40, label, ha="center", va="center", weight="bold", color=DARK)
        ax.text(x, -.01, role, ha="center", fontsize=7.1,
                color=BLUE if selected else GRAY)
    for x in range(3):
        arrow(ax, (x + .18, .40), (x + .82, .40), GRAY, lw=1.0)
    for start, end, rad, text, tx in [
        (1, 0, -.38, r"$\neg C^{\rho}_{uf}(0,1)$", .48),
        (1, 2, .38, r"$\neg C^{\rho}_{fc}(1,0)$", 1.55),
    ]:
        ax.add_patch(FancyArrowPatch((start, .67), (end, .67),
                     connectionstyle=f"arc3,rad={rad}", arrowstyle="-|>",
                     mutation_scale=9, lw=1.25, color=BLUE, linestyle="--"))
        ax.text(tx, .99, text, ha="center", fontsize=7.4, color=DARK)
    ax.text(2.60, .69, r"$C^{\rho}_{co}(1,0)=1$", ha="center", fontsize=7.3, color=GREEN)
    ax.text(-.46, -.34,
            r"Internal checks: $C^{\rho}_{uf}(1,1)=C^{\rho}_{fc}(1,1)=1$",
            fontsize=7.2, color=GREEN)
    ax.text(-.46, -.65,
            r"$F=\{f\}\Rightarrow R^{*}_{\rho}=\{u,f,c\}$ if $\{u,c\}\cap M=\varnothing$",
            fontsize=7.8, color=DARK)
    ax.text(-.46, -.96, r"If $u\in M$, closure reaches an immutable node: reject $\rho$.",
            fontsize=7.5, color=ORANGE)
    fig.subplots_adjust(left=.02, right=.99, top=.98, bottom=.02)
    fig.savefig(OUT / "repair_obligations.pdf")
    plt.close(fig)


def certificate():
    fig, ax = plt.subplots(figsize=(3.45, 2.30))
    ax.set(xlim=(0, 10), ylim=(0, 6.8))
    ax.axis("off")
    ax.text(.12, 6.48, "Observed-input evidence certifies a sparse route",
            fontsize=8.2, weight="bold", color=DARK)

    for x, lab, sub in [(1.1, "$X_0$", "input"), (5.0, "$X_1$", "middle"), (8.9, "$X_2$", "result")]:
        ax.scatter(x, 5.54, s=380, facecolor=LIGHT_BLUE, edgecolor=BLUE,
                   linewidth=1.2, zorder=3)
        ax.text(x, 5.54, lab, ha="center", va="center", weight="bold")
        ax.text(x, 4.76, sub, ha="center", fontsize=6.8, color=GRAY)
    arrow(ax, (1.55, 5.54), (4.55, 5.54), BLUE)
    arrow(ax, (5.45, 5.54), (8.45, 5.54), BLUE)
    ax.text(3.05, 5.91, r"$X_0\rightarrow X_1$", ha="center", fontsize=7.0)
    ax.text(6.95, 5.91, r"$X_1\rightarrow X_2$", ha="center", fontsize=7.0)

    columns = [r"$X_0$", r"$X_1$", r"$X_2$"]
    rows = [["a", "u", "v"], ["b", "NULL", "w"]]
    table = ax.table(cellText=rows, colLabels=columns, cellLoc="center",
                     colLoc="center", bbox=[.18, .37, .64, .32])
    table.auto_set_font_size(False)
    table.set_fontsize(7.2)
    for (row, col), cell in table.get_celld().items():
        cell.set_linewidth(.55)
        cell.set_edgecolor(GRAY)
        if row == 0:
            cell.set_facecolor(LIGHT_BLUE)
            cell.set_text_props(weight="bold")
        elif row == 1:
            cell.set_facecolor(LIGHT_GREEN)

    ax.text(5.0, 2.16, r"Direct target dependency: $X_0\rightarrow X_2$",
            ha="center", va="center", fontsize=7.0, color=DARK)

    box(ax, .25, .25, 4.35, 1.62,
        "Global certificate\nREJECT\nrow b has no middle value",
        ORANGE, "#FFF4EC", fs=6.9)
    box(ax, 5.40, .25, 4.35, 1.62,
        "Observed input a\nADMIT\nrow (a,u,v) is a witness",
        GREEN, LIGHT_GREEN, fs=6.9)
    fig.subplots_adjust(left=.02, right=.98, top=.98, bottom=.02)
    fig.savefig(OUT / "input_index_certificate_adjusted.pdf")
    plt.close(fig)


def results_overview():
    fig, axes = plt.subplots(1, 3, figsize=(7.10, 2.48),
                             gridspec_kw={"width_ratios": [1.18, .78, 1.22]},
                             layout="constrained")

    # (a) Safety frontier over every defined path-input pair.
    ax = axes[0]
    names = ["Global", "Observed\ninput", "Type only"]
    safe = np.array([25665, 30739, 30739])
    wrong = np.array([0, 0, 826])
    x = np.arange(3)
    bars = ax.bar(x, safe, color=["#EEF1F3", LIGHT_GREEN, LIGHT_BLUE],
                  edgecolor=[GRAY, GREEN, BLUE], linewidth=1.1)
    ax.bar([2], [wrong[2]], bottom=[safe[2]], color="#FFF4EC",
           edgecolor=ORANGE, linewidth=1.0, hatch="////")
    ax.set_title("(a) Admission safety (31,565 pairs)", loc="left", weight="bold",
                 fontsize=7.8)
    ax.set_ylabel("Path-input pairs")
    ax.set_xticks(x, names)
    ax.set_ylim(0, 37000)
    ax.set_yticks([0, 10000, 20000, 30000])
    ax.grid(axis="y", color="#D9DEE3", lw=.5, zorder=0)
    for i, (b, s, wrong_n) in enumerate(zip(bars, safe, wrong)):
        ax.text(b.get_x() + b.get_width()/2, s - 1350, f"{s:,}",
                ha="center", va="top", fontsize=6.8, weight="bold", color=DARK)
        if wrong_n:
            ax.text(i, s + wrong_n + 600, f"{wrong_n} wrong", ha="center",
                    va="bottom", fontsize=6.5, weight="bold", color=ORANGE)

    # (b) Independent-task confirmation.
    ax = axes[1]
    vals = [39 / 72 * 100, 58 / 72 * 100]
    bars = ax.bar([0, 1], vals, width=.62,
                  color=["#EEF1F3", LIGHT_GREEN],
                  edgecolor=[GRAY, GREEN], linewidth=1.1)
    ax.set_title("(b) Task completion ($n=72$)", loc="left", weight="bold",
                 fontsize=7.8)
    ax.set_ylabel("Passed tasks (%)")
    ax.set_xticks([0, 1], ["Native", "ICR\nadvice"])
    ax.set_ylim(0, 100)
    ax.grid(axis="y", color="#D9DEE3", lw=.5, zorder=0)
    for b, lab in zip(bars, ["39/72", "58/72"]):
        ax.text(b.get_x() + b.get_width()/2, b.get_height() + 3, lab,
                ha="center", fontsize=7.0, weight="bold")

    # (c) Identical-prefix confirmation.
    ax = axes[2]
    labels = ["Global", "Type only", "Observed\ninput"]
    local = np.array([7, 19, 19]) / 20 * 100
    whole = np.array([6, 18, 19]) / 20 * 100
    xx = np.arange(3)
    w = .34
    b1 = ax.bar(xx - w/2, local, w, color=LIGHT_BLUE, edgecolor=BLUE, linewidth=1.0,
                label="Target restored")
    b2 = ax.bar(xx + w/2, whole, w, color=LIGHT_GREEN, edgecolor=GREEN,
                linewidth=1.0, hatch="///", label="Whole task")
    ax.set_title("(c) Same-prefix recovery ($n=20$)", loc="left", weight="bold",
                 fontsize=7.8)
    ax.set_ylabel("Successful prefixes (%)")
    ax.set_xticks(xx, labels)
    ax.set_ylim(0, 112)
    ax.grid(axis="y", color="#D9DEE3", lw=.5, zorder=0)
    for bars, labs in [(b1, ["7", "19", "19"]), (b2, ["6", "18", "19"])]:
        for b, lab in zip(bars, labs):
            ax.text(b.get_x() + b.get_width()/2, b.get_height() + 2.4, lab,
                    ha="center", fontsize=6.6, weight="bold")
    ax.legend(frameon=False, loc="upper left", handlelength=1.2,
              labels=["Target", "Task"])

    for ax in axes:
        ax.tick_params(length=2.5, width=.6)
        ax.set_axisbelow(True)
    fig.savefig(OUT / "results_overview.pdf")
    plt.close(fig)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    style()
    workflow()
    obligations()
    certificate()
    results_overview()


if __name__ == "__main__":
    main()
