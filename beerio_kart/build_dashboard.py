"""Builds the interactive Excel dashboard for the league.

    python3 -m beerio_kart.build_dashboard

Writes ``beerio_kart/dashboard/Beerio_Kart_Dashboard.xlsx`` with:

- **Overview**: how the model works, how to use the workbook.
- **Roster**: every player's skill breakdown (fitted / adjustment /
  effective), with two live-editable input columns.
- **ResultsLog**: every historical race result, as a filterable table.
- **PlayoffOdds**: the Monte Carlo championship-odds table + chart.
- **SeasonSnapshot**: one full illustrative simulated season.
- **PlayerDetail**: pick a player from a dropdown, see their summary
  stats and full chronological result history + trend chart.

The Monte Carlo table and season snapshot are a snapshot of one specific
Python run (sims/seed are printed on the Overview tab and in a footnote
under the table) -- Excel can't re-run the underlying simulator, so
editing Roster's input cells doesn't recompute PlayoffOdds by itself.
Everything that *can* be a live formula (Roster's effective skill, games
played, real average points, all of PlayerDetail's lookups) is one.
"""
from __future__ import annotations

import datetime
import random

from openpyxl import Workbook
from openpyxl.chart import BarChart, LineChart, Reference
from openpyxl.formatting.rule import DataBarRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.table import Table, TableStyleInfo

import yaml

from .build_roster_from_history import build_skill_breakdown
from .data.history import SEASON_2_GROUPS
from .data.history_points import (
    SEASON_1_PLAYOFF_POINTS,
    SEASON_1_WEEKLY_POINTS,
    SEASON_2_WEEK_1_POINTS,
)
from .match import MatchConfig
from .models import Player
from .monte_carlo import run_monte_carlo
from .season import run_season

FONT_NAME = "Arial"
SIMS = 20000
MC_SEED = 42
SNAPSHOT_SEED = 7
OUT_PATH = "beerio_kart/dashboard/Beerio_Kart_Dashboard.xlsx"
ROSTER_YAML = "beerio_kart/config/players_calibrated.yaml"

INPUT_FILL = PatternFill("solid", fgColor="DDEBFF")
INPUT_FONT = Font(name=FONT_NAME, color="0000FF")
COMPUTED_FILL = PatternFill("solid", fgColor="F2F2F2")
HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
HEADER_FONT = Font(name=FONT_NAME, bold=True, color="FFFFFF")
TITLE_FONT = Font(name=FONT_NAME, bold=True, size=16)
SECTION_FONT = Font(name=FONT_NAME, bold=True, size=12)
BODY_FONT = Font(name=FONT_NAME, size=10)
BOLD_BODY_FONT = Font(name=FONT_NAME, size=10, bold=True)
THIN = Side(style="thin", color="BFBFBF")
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)


def cell(ws, row, col, value=None, font=BODY_FONT, fill=None, fmt=None, align=None, border=True):
    c = ws.cell(row=row, column=col, value=value)
    c.font = font
    if fill:
        c.fill = fill
    if fmt:
        c.number_format = fmt
    if align:
        c.alignment = align
    if border:
        c.border = BOX
    return c


def header_row(ws, row, headers, start_col=1):
    for i, h in enumerate(headers):
        cell(ws, row, start_col + i, h, font=HEADER_FONT, fill=HEADER_FILL, align=Alignment(horizontal="center"))


def autosize(ws, widths):
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w


def make_table(ws, name, ref):
    table = Table(displayName=name, ref=ref)
    table.tableStyleInfo = TableStyleInfo(
        name="TableStyleMedium2", showRowStripes=True, showFirstColumn=False
    )
    ws.add_table(table)


# ---------------------------------------------------------------------------
# Data assembly
# ---------------------------------------------------------------------------


def assemble_results_log():
    events = (
        [(label, results, "Season 1 - Weekly") for label, results in SEASON_1_WEEKLY_POINTS]
        + [(label, results, "Season 1 - Playoffs") for label, results in SEASON_1_PLAYOFF_POINTS]
        + [(label, results, "Season 2 - Week 1") for label, results in SEASON_2_WEEK_1_POINTS]
    )
    rows = []
    for label, results, phase in events:
        for placement, (pid, points) in enumerate(results, start=1):
            rows.append((label, phase, pid, placement, points))
    return rows


def load_groups_plain_ids(path: str) -> dict[str, list[Player]]:
    """Like roster.load_roster, but ids are the bare player name (no
    group prefix) -- this dashboard's ResultsLog/Roster/PlayoffOdds sheets
    all key off plain names, and every real name here is already unique
    across the whole 16-player roster, so the prefix roster.py normally
    adds for safety would only make season-snapshot output harder to read.
    """
    with open(path) as f:
        data = yaml.safe_load(f)
    return {
        group_name: [
            Player(id=e["name"], name=e["name"], skill=float(e.get("skill", 1000.0))) for e in entries
        ]
        for group_name, entries in data["groups"].items()
    }


# ---------------------------------------------------------------------------
# Sheet builders
# ---------------------------------------------------------------------------


def build_overview(wb, generated_at):
    ws = wb.active
    ws.title = "Overview"
    autosize(ws, [28, 90])

    cell(ws, 1, 1, "Beerio Kart League Dashboard", font=TITLE_FONT, border=False)
    cell(
        ws, 2, 1,
        "Predictive model + real-history skill calibration",
        font=Font(name=FONT_NAME, italic=True, size=11), border=False,
    )

    r = 4
    cell(ws, r, 1, "Generated", font=BOLD_BODY_FONT, border=False)
    cell(ws, r, 2, generated_at, border=False)
    r += 1
    cell(ws, r, 1, "Monte Carlo sims / seed", font=BOLD_BODY_FONT, border=False)
    cell(ws, r, 2, f"{SIMS:,} simulated seasons, seed={MC_SEED}", border=False)
    r += 1
    cell(ws, r, 1, "Snapshot season seed", font=BOLD_BODY_FONT, border=False)
    cell(ws, r, 2, str(SNAPSHOT_SEED), border=False)

    r += 2
    cell(ws, r, 1, "League format", font=SECTION_FONT, border=False)
    r += 1
    facts = [
        "16 players in 4 fixed groups of 4 (A-D).",
        "Each group plays a match once a month for 3 months; standings are total points across those 3 matches.",
        "Each match races Mario Kart Wii's full 32-race GP structure (8 cups x 4 tracks), MKWii's own"
        " points table for a 4-driver field: 1st=15, 2nd=12, 3rd=10, 4th=8.",
        "Each player must drink 8 beers across their match's 32 races; a random selector decides which"
        " races trigger each beer, and accumulated impairment drags down effective skill for the rest"
        " of that match.",
        "Top 2 from each group (8 total) make the playoffs, seeded 1-8 by season points.",
        "Seeds {1,2,7,8} race as one 4-way free-for-all; seeds {3,4,5,6} race as another. Top 2 from"
        " EACH of those two matches (4 players total) advance to a single winner-take-all final.",
    ]
    for fact in facts:
        cell(ws, r, 1, f"• {fact}", border=False)
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=2)
        ws.cell(row=r, column=1).alignment = Alignment(wrap_text=True, vertical="top")
        ws.row_dimensions[r].height = 30
        r += 1

    r += 1
    cell(ws, r, 1, "How to use this workbook", font=SECTION_FONT, border=False)
    r += 1
    howto = [
        "Roster tab: blue cells (Adjustment Multiplier, Manual Override) are meant to be edited."
        " Everything else on that tab (Effective Skill, Games, Avg Points) recalculates live from them"
        " and from the ResultsLog tab.",
        "PlayoffOdds and SeasonSnapshot are a SNAPSHOT from one specific Python run (see sims/seed"
        " above) -- Excel can't re-run the Monte Carlo simulator itself. After changing Roster inputs,"
        " ask for the model to be re-run to refresh these tabs.",
        "ResultsLog is a plain filterable table (click the column header arrows) of every real result"
        " behind the skill ratings.",
        "PlayerDetail: pick a player from the dropdown in cell B2 to see their summary stats and their"
        " full chronological result history with a trend chart.",
    ]
    for note in howto:
        cell(ws, r, 1, f"• {note}", border=False)
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=2)
        ws.cell(row=r, column=1).alignment = Alignment(wrap_text=True, vertical="top")
        ws.row_dimensions[r].height = 30
        r += 1

    r += 1
    cell(ws, r, 1, "Legend", font=SECTION_FONT, border=False)
    r += 1
    cell(ws, r, 1, "Editable input", font=INPUT_FONT, fill=INPUT_FILL)
    cell(ws, r, 2, "Change this to explore a what-if -- e.g. a new form adjustment.", border=False)
    r += 1
    cell(ws, r, 1, "Computed externally", fill=COMPUTED_FILL)
    cell(
        ws, r, 2,
        "Value from the Python model (Plackett-Luce fit or Monte Carlo run), not a live"
        " Excel formula -- rerun the model to refresh it.",
        border=False,
    )
    r += 1
    cell(ws, r, 1, "Formula")
    cell(ws, r, 2, "Live Excel formula; recalculates automatically.", border=False)


def build_roster_sheet(wb, breakdown, effective_by_id):
    ws = wb.create_sheet("Roster")
    headers = [
        "Group", "Player", "Fitted Skill", "Adjustment Multiplier", "Manual Override",
        "Effective Skill", "Games (History)", "Avg Points (Real)", "Notes",
    ]
    header_row(ws, 1, headers)

    rostered = [(g, pid) for g, members in SEASON_2_GROUPS.items() for pid in members]
    rostered.sort(key=lambda gp: (gp[0], -effective_by_id[gp[1]]))

    row = 2
    for group, pid in rostered:
        b = breakdown[pid]
        cell(ws, row, 1, group)
        cell(ws, row, 2, pid, font=BOLD_BODY_FONT)
        cell(ws, row, 3, b.fitted, fill=COMPUTED_FILL, fmt="#,##0.0")
        cell(ws, row, 4, b.multiplier, font=INPUT_FONT, fill=INPUT_FILL, fmt="0.00")
        cell(ws, row, 5, b.manual_override, font=INPUT_FONT, fill=INPUT_FILL, fmt="#,##0.0")
        cell(ws, row, 6, f"=IF(E{row}=\"\",C{row}*D{row},E{row})", fmt="#,##0.0")
        cell(ws, row, 7, f'=COUNTIF(ResultsLog!$C$2:$C$61,B{row})')
        cell(ws, row, 8, f'=IFERROR(AVERAGEIF(ResultsLog!$C$2:$C$61,B{row},ResultsLog!$E$2:$E$61),"n/a")', fmt="#,##0.0")
        note = ""
        if b.manual_override is not None:
            note = "No race history yet -- manual estimate (see league read)."
        elif b.multiplier != 1.0:
            note = f"Form-adjusted x{b.multiplier}: fitted skill understates recent improvement."
        cell(ws, row, 9, note)
        row += 1

    last_row = row - 1
    make_table(ws, "RosterTable", f"A1:I{last_row}")
    autosize(ws, [8, 12, 13, 20, 16, 15, 15, 16, 55])

    row += 1
    cell(
        ws, row, 1,
        "Fitted Skill: recency-weighted Plackett-Luce MLE over all recorded results"
        " (beerio_kart.calibrate). Rerun `python3 -m beerio_kart.build_roster_from_history`"
        " after editing the blue cells to regenerate config/players_calibrated.yaml, then rerun"
        " the Monte Carlo simulator to refresh the PlayoffOdds tab.",
        border=False,
    )
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=9)
    ws.cell(row=row, column=1).alignment = Alignment(wrap_text=True)
    ws.row_dimensions[row].height = 30


def build_results_log_sheet(wb):
    ws = wb.create_sheet("ResultsLog")
    header_row(ws, 1, ["Event", "Phase", "Player", "Placement", "Points"])
    rows = assemble_results_log()
    for i, (label, phase, pid, placement, points) in enumerate(rows, start=2):
        cell(ws, i, 1, label)
        cell(ws, i, 2, phase)
        cell(ws, i, 3, pid)
        cell(ws, i, 4, placement, fmt="0")
        cell(ws, i, 5, points, fmt="#,##0")
    last_row = 1 + len(rows)
    make_table(ws, "ResultsLogTable", f"A1:E{last_row}")
    autosize(ws, [20, 20, 14, 12, 10])
    return last_row


def build_playoff_odds_sheet(wb, mc_stats):
    ws = wb.create_sheet("PlayoffOdds")
    headers = ["Player", "Group", "Effective Skill", "Avg Season Points (sim)", "Playoff %", "Finals %", "Championship %"]
    header_row(ws, 1, headers)

    ranked = sorted(mc_stats.items(), key=lambda kv: -kv[1].championships)
    row = 2
    for pid, s in ranked:
        r = s.as_row()
        cell(ws, row, 1, pid, font=BOLD_BODY_FONT)
        cell(ws, row, 2, f'=INDEX(Roster!A:A,MATCH(A{row},Roster!B:B,0))')
        cell(ws, row, 3, f'=INDEX(Roster!F:F,MATCH(A{row},Roster!B:B,0))', fmt="#,##0.0")
        cell(ws, row, 4, r["avg_points"], fmt="#,##0.0")
        cell(ws, row, 5, r["playoff_pct"] / 100.0, fmt="0.0%")
        cell(ws, row, 6, r["finals_pct"] / 100.0, fmt="0.0%")
        cell(ws, row, 7, r["champion_pct"] / 100.0, fmt="0.0%")
        row += 1
    last_row = row - 1
    make_table(ws, "PlayoffOddsTable", f"A1:G{last_row}")
    autosize(ws, [12, 8, 15, 22, 12, 12, 16])

    for col in ("E", "F", "G"):
        ws.conditional_formatting.add(
            f"{col}2:{col}{last_row}",
            DataBarRule(start_type="num", start_value=0, end_type="num", end_value=1, color="638EC6"),
        )

    note_row = last_row + 2
    cell(
        ws, note_row, 1,
        f"Monte Carlo snapshot: {SIMS:,} simulated seasons, seed={MC_SEED}, using"
        f" config/players_calibrated.yaml as generated. Rerun"
        f" `python3 -m beerio_kart.cli --config {ROSTER_YAML} --sims {SIMS} --seed {MC_SEED}`"
        " to refresh after changing skills.",
        border=False,
    )
    ws.merge_cells(start_row=note_row, start_column=1, end_row=note_row, end_column=7)
    ws.cell(row=note_row, column=1).alignment = Alignment(wrap_text=True)
    ws.row_dimensions[note_row].height = 30

    chart = BarChart()
    chart.title = "Championship odds"
    chart.y_axis.title = "Championship %"
    chart.y_axis.numFmt = "0%"
    chart.style = 10
    data = Reference(ws, min_col=7, min_row=1, max_row=last_row)
    cats = Reference(ws, min_col=1, min_row=2, max_row=last_row)
    chart.add_data(data, titles_from_data=True)
    chart.set_categories(cats)
    chart.width = 24
    chart.height = 12
    ws.add_chart(chart, f"I2")


def build_season_snapshot_sheet(wb, season_result):
    ws = wb.create_sheet("SeasonSnapshot")
    autosize(ws, [10, 8, 14, 10, 16])
    row = 1
    cell(
        ws, row, 1, f"Illustrative simulated season (one draw, seed={SNAPSHOT_SEED})",
        font=TITLE_FONT, border=False,
    )
    row += 1
    cell(
        ws, row, 1,
        "One random outcome, not a prediction on its own -- see PlayoffOdds for odds across"
        f" {SIMS:,} draws.",
        font=Font(name=FONT_NAME, italic=True, size=10), border=False,
    )
    row += 2

    cell(ws, row, 1, "League phase", font=SECTION_FONT, border=False)
    row += 1
    for group_name, group in season_result.groups.items():
        cell(ws, row, 1, f"Group {group_name}", font=BOLD_BODY_FONT, border=False)
        row += 1
        header_row(ws, row, ["Rank", "Player", "Points", "Advances"])
        row += 1
        for rank, pid in enumerate(group.standings(), start=1):
            cell(ws, row, 1, rank, fmt="0")
            cell(ws, row, 2, pid)
            cell(ws, row, 3, group.season_points[pid], fmt="#,##0")
            cell(ws, row, 4, "Yes" if rank <= 2 else "")
            row += 1
        row += 1

    playoffs = season_result.playoffs
    cell(ws, row, 1, "Playoffs", font=SECTION_FONT, border=False)
    row += 1
    cell(ws, row, 1, "Seeds", font=BOLD_BODY_FONT, border=False)
    row += 1
    header_row(ws, row, ["Seed", "Player"])
    row += 1
    for i, pid in enumerate(playoffs.seeds, start=1):
        cell(ws, row, 1, i, fmt="0")
        cell(ws, row, 2, pid)
        row += 1
    row += 1

    def bracket_table(title, match_result):
        nonlocal row
        cell(ws, row, 1, title, font=BOLD_BODY_FONT, border=False)
        row += 1
        header_row(ws, row, ["Rank", "Player", "Points", "Advances"])
        row += 1
        ranked = match_result.ranked()
        for rank, pid in enumerate(ranked, start=1):
            cell(ws, row, 1, rank, fmt="0")
            cell(ws, row, 2, pid)
            cell(ws, row, 3, match_result.points[pid], fmt="#,##0")
            cell(ws, row, 4, "Yes" if rank <= 2 else "")
            row += 1
        row += 1

    bracket_table("Bracket: seeds 1, 2, 7, 8", playoffs.bracket_top)
    bracket_table("Bracket: seeds 3, 4, 5, 6", playoffs.bracket_bottom)
    bracket_table("Final (winner takes all)", playoffs.final)

    cell(ws, row, 1, "CHAMPION", font=BOLD_BODY_FONT, fill=HEADER_FILL, border=False)
    champ_font = Font(name=FONT_NAME, bold=True, size=14, color="1F4E78")
    ws.cell(row=row, column=1).font = HEADER_FONT
    cell(ws, row, 2, playoffs.champion, font=champ_font, border=False)


def build_player_detail_sheet(wb, player_ids, results_last_row, max_games):
    ws = wb.create_sheet("PlayerDetail")
    autosize(ws, [22, 26, 12])

    cell(ws, 1, 1, "Select a player", font=SECTION_FONT, border=False)
    dv_sheet = wb.create_sheet("Lists")
    dv_sheet.sheet_state = "hidden"
    for i, pid in enumerate(sorted(player_ids), start=1):
        dv_sheet.cell(row=i, column=1, value=pid)
    dv = DataValidation(
        type="list", formula1=f"=Lists!$A$1:$A${len(player_ids)}", allow_blank=False
    )
    ws.add_data_validation(dv)
    default_player = "Kannon" if "Kannon" in player_ids else sorted(player_ids)[0]
    cell(ws, 2, 1, default_player, font=Font(name=FONT_NAME, bold=True, size=13), fill=INPUT_FILL)
    dv.add(ws["A2"])

    labels = ["Group", "Effective Skill", "Games (History)", "Avg Points (Real)", "Playoff %", "Finals %", "Championship %"]
    formulas = [
        '=INDEX(Roster!A:A,MATCH($A$2,Roster!B:B,0))',
        '=INDEX(Roster!F:F,MATCH($A$2,Roster!B:B,0))',
        '=INDEX(Roster!G:G,MATCH($A$2,Roster!B:B,0))',
        '=INDEX(Roster!H:H,MATCH($A$2,Roster!B:B,0))',
        '=IFERROR(INDEX(PlayoffOdds!E:E,MATCH($A$2,PlayoffOdds!A:A,0)),"n/a")',
        '=IFERROR(INDEX(PlayoffOdds!F:F,MATCH($A$2,PlayoffOdds!A:A,0)),"n/a")',
        '=IFERROR(INDEX(PlayoffOdds!G:G,MATCH($A$2,PlayoffOdds!A:A,0)),"n/a")',
    ]
    fmts = [None, "#,##0.0", "0", "#,##0.0", "0.0%", "0.0%", "0.0%"]
    row = 4
    for label, formula, fmt in zip(labels, formulas, fmts):
        cell(ws, row, 1, label, font=BOLD_BODY_FONT)
        cell(ws, row, 2, formula, fmt=fmt)
        row += 1

    row += 1
    cell(ws, row, 1, "Chronological result history", font=SECTION_FONT, border=False)
    row += 1
    table_start = row
    header_row(ws, row, ["#", "Event", "Points"])
    row += 1
    first_data_row = row
    for k in range(1, max_games + 1):
        rel_row_expr = (
            f"AGGREGATE(15,6,(ROW(ResultsLog!$C$2:$C${results_last_row})"
            f"-ROW(ResultsLog!$C$2)+1)/(ResultsLog!$C$2:$C${results_last_row}=$A$2),{k})"
        )
        cell(ws, row, 1, k, fmt="0")
        cell(ws, row, 2, f'=IFERROR(INDEX(ResultsLog!$A$2:$A${results_last_row},{rel_row_expr}),"")')
        cell(ws, row, 3, f'=IFERROR(INDEX(ResultsLog!$E$2:$E${results_last_row},{rel_row_expr}),NA())', fmt="#,##0")
        row += 1
    last_data_row = row - 1
    make_table(ws, "PlayerDetailTable", f"A{table_start}:C{last_data_row}")

    chart = LineChart()
    chart.title = "Points by appearance (chronological)"
    chart.y_axis.title = "Points"
    chart.x_axis.title = "Appearance #"
    chart.style = 10
    data = Reference(ws, min_col=3, min_row=table_start, max_row=last_data_row)
    cats = Reference(ws, min_col=1, min_row=first_data_row, max_row=last_data_row)
    chart.add_data(data, titles_from_data=True)
    chart.set_categories(cats)
    chart.width = 20
    chart.height = 10
    ws.add_chart(chart, f"E4")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    breakdown = build_skill_breakdown()
    effective_by_id = {pid: b.effective for pid, b in breakdown.items()}

    groups = load_groups_plain_ids(ROSTER_YAML)
    config = MatchConfig()

    mc_rng = random.Random(MC_SEED)
    mc_stats = run_monte_carlo(groups, config, SIMS, mc_rng)
    # monte_carlo keys by the roster's internal ids ("A_Kannon"); rekey by
    # display name to match ResultsLog/Roster, which use plain names.
    mc_stats = {s.name: s for s in mc_stats.values()}

    snapshot_rng = random.Random(SNAPSHOT_SEED)
    snapshot_groups = {name: list(players) for name, players in groups.items()}
    season_result = run_season(snapshot_groups, config, snapshot_rng)

    results_rows = assemble_results_log()
    from collections import Counter

    games_played = Counter(pid for _label, _phase, pid, _placement, _points in results_rows)
    max_games = max(games_played.values())

    generated_at = datetime.date.today().isoformat()

    wb = Workbook()
    build_overview(wb, generated_at)
    build_roster_sheet(wb, breakdown, effective_by_id)
    results_last_row = build_results_log_sheet(wb)
    build_playoff_odds_sheet(wb, mc_stats)
    build_season_snapshot_sheet(wb, season_result)
    build_player_detail_sheet(wb, set(effective_by_id), results_last_row, max_games)

    wb.move_sheet("Lists", offset=len(wb.sheetnames))

    import os

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    wb.save(OUT_PATH)
    print(f"Wrote {OUT_PATH}")


if __name__ == "__main__":
    main()
