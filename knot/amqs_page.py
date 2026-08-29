"""AMQS-NDX 스냅샷 → 단일 HTML 페이지.

외부 의존성 없이 문자열로 전체 문서를 만든다(서버로도, 파일로도 그대로 쓴다).
데이터가 없어도 페이지는 그려지고, 비어 있는 자리는 '—' 로 표시한다.
"""
from __future__ import annotations

import html
from typing import Any

ACCENT = {"Risk-On": "up", "Neutral": "warn", "Risk-Off": "down", "Unknown": "muted"}
SIGNAL_CLS = {"CORE": "up", "SATELLITE": "", "EXIT": "down", "WATCH": "muted", "—": "muted"}


# ─────────────────────── 포맷 헬퍼 ───────────────────────
def _e(v: Any) -> str:
    return html.escape(str(v), quote=True)


def num(v: Any, digits: int = 2, suffix: str = "") -> str:
    if v is None:
        return "—"
    try:
        return f"{float(v):,.{digits}f}{suffix}"
    except (TypeError, ValueError):
        return _e(v)


def pct(v: Any, digits: int = 2) -> str:
    return "—" if v is None else f"{float(v):+.{digits}f}%"


def signed(v: Any, digits: int = 2) -> str:
    """부호에 따라 색이 붙는 퍼센트."""
    if v is None:
        return '<span class="muted">—</span>'
    cls = "up" if float(v) > 0 else "down" if float(v) < 0 else "muted"
    return f'<span class="{cls}">{pct(v, digits)}</span>'


def bar(ratio: float) -> str:
    width = max(0.0, min(1.0, ratio)) * 100
    return f'<div class="bar"><span style="width:{width:.1f}%"></span></div>'


def tile(label: str, value: str, sub: str = "", cls: str = "") -> str:
    return (f'<div class="tile"><div class="tile-l">{label}</div>'
            f'<div class="tile-v {cls}">{value}</div>'
            f'<div class="tile-s">{sub}</div></div>')


def card(title: str, body: str) -> str:
    return f'<section class="card"><h2>{_e(title)}</h2>{body}</section>'


# ─────────────────────── 섹션 ───────────────────────
def sec_regime(s: dict) -> str:
    r, rules = s["regime"], s["rules"]
    cls = ACCENT.get(r["regime"], "muted")
    exp = f'{r["exposure"]:.0%} 투자' if r["exposure"] else "판정 불가"
    vix_sub = ("Risk-On 구간" if (r["vix"] is not None and r["vix"] < rules["vix_risk_on"])
               else "리스크 회피 구간" if r["vix"] is not None else "데이터 없음")
    tiles = "".join([
        tile("레짐", _e(r["regime"]), exp, cls),
        tile("QQQ", num(r["price"]), f'200MA {num(r["sma200"])}'),
        tile("VIX", num(r["vix"], 1), vix_sub),
        tile("QQQ 5D", pct(r["mom_5d"]), f'SPY {pct(r["bench_5d"])}',
             "up" if (r["mom_5d"] or 0) > 0 else "down"),
    ])
    body = f"""
<p>AMQS-NDX는 AMQS-BIO의 XBI 대신 <b>Invesco QQQ Trust (QQQ)</b>를 레짐 벤치마크로 씁니다.
QQQ는 나스닥100 시가총액 가중이라 대형 성장주의 추세를 그대로 반영하고,
개별 종목 채점의 상대강도(RS) 기준선 역할도 함께 합니다.</p>
<div class="tiles">{tiles}</div>
<p class="verdict"><b class="{cls}">{_e(r["regime"])}</b> — {_e(r["verdict"])}</p>
<p class="mono small muted">판정: {_e(" · ".join(r["reasons"]))}</p>
<div class="scroll"><table class="mini">
<tr><th>레짐</th><th>조건</th><th>투자비중</th></tr>
<tr><td class="up">Risk-On</td><td>QQQ ≥ 200MA <b>그리고</b> VIX &lt; {num(rules['vix_risk_on'], 0)}</td><td class="mono">100%</td></tr>
<tr><td class="warn">Neutral</td><td>둘 중 하나만 충족</td><td class="mono">60%</td></tr>
<tr><td class="down">Risk-Off</td><td>둘 다 불충족 <b>또는</b> VIX ≥ {num(rules['vix_risk_off'], 0)}</td><td class="mono">25%</td></tr>
<tr><td class="muted">급락 가드</td><td>QQQ 5일 수익률 ≤ {num(rules['crash_5d'], 0)}%</td><td class="mono">한 단계 강등</td></tr>
</table></div>"""
    return card("거시 레짐 · QQQ", body)


def sec_macro(s: dict) -> str:
    m, segs = s["macro"], s["segments"]
    rate_cls = "down" if m["rate_pressure"] > 0.25 else "up" if m["rate_pressure"] < -0.25 else "muted"
    risk_cls = "up" if m["risk_appetite"] > 0.25 else "down" if m["risk_appetite"] < -0.25 else "muted"
    spx = m.get("spx_above_200ma")
    tiles = "".join([
        tile("10Y (TNX)", num(m["tnx"], 2), "미 국채 10년"),
        tile("TNX 60일", pct(m["tnx_60d"], 1), _e(m["labels"].get("rate", "")), rate_cls),
        tile("SPX vs 200MA", "위" if spx else ("아래" if spx is False else "—"),
             f'200MA {num(m.get("spx_ma200"))}',
             "up" if spx else "down" if spx is False else "muted"),
        tile("리스크 선호", _e(m["labels"].get("risk", "—")), f'VIX {num(m["vix"], 1)}', risk_cls),
    ])
    rows = "".join(
        f'<tr><td>{_e(k)}</td><td class="mono">{v.get("duration", 1):.2f}</td>'
        f'<td class="mono">{v.get("beta", 1):.2f}</td>'
        f'<td class="small muted wrap">{_e(v.get("note", ""))}</td></tr>'
        for k, v in segs.items())
    notes = ("<p class='small muted'>" + " · ".join(_e(n) for n in m["notes"]) + "</p>") if m["notes"] else ""
    body = f"""
<p>AMQS-NDX는 100점 채점 중 <b>거시 적합성 {s['factor_weights']['macro']}%</b>를 배정합니다
(바이오판 AMQS-BIO는 25%). 바이오와 달리 나스닥은 금리보다 캡엑스·실적 사이클의 영향이 크기 때문입니다.
<b>10Y 국채수익률(TNX) 60일 추세</b>와 SPX 200일선, VIX가 세그먼트별 macro 점수를 조정합니다.
60일 +15% 이상 상승이면 금리 압력 +1(만점), −15%면 −1로 봅니다.</p>
<div class="tiles">{tiles}</div>
{notes}
<p class="mono small">macro = 5 − 3 × 금리압력({m["rate_pressure"]:+.2f}) × 듀레이션
+ 2 × 리스크선호({m["risk_appetite"]:+.2f}) × 베타 &nbsp;(0~10점으로 절단)</p>
<div class="scroll"><table>
<tr><th>세그먼트</th><th>듀레이션</th><th>베타</th><th class="wrap">성격</th></tr>{rows}
</table></div>"""
    return card("금리 · 거시 적합성", body)


def sec_factors(s: dict) -> str:
    w = s["factor_weights"]
    body = f"""
<p>유니버스 {s['universe_count']}종을 매일 같은 잣대로 줄 세웁니다. 각 지표는 절대값이 아니라
<b>유니버스 내 백분위</b>로 환산해 배점을 곱합니다 — 시장 전체가 밀릴 때도 상대 서열은 유지됩니다.</p>
<div class="scroll"><table>
<tr><th>팩터</th><th>배점</th><th>구성</th><th class="wrap">왜</th></tr>
<tr><td><b>모멘텀</b></td><td class="mono">{w['momentum']}</td>
    <td>12-1M 20 · 6M 12 · 1M 8</td>
    <td class="small muted wrap">12-1은 최근 1개월을 뺀 12개월 수익률 — 단기 반전 노이즈 제거</td></tr>
<tr><td><b>추세</b></td><td class="mono">{w['trend']}</td>
    <td>200MA 이격 10 · 골든크로스 7 · 52주 고점 근접 8</td>
    <td class="small muted wrap">추세 위에 있는 종목만 모멘텀이 이어진다</td></tr>
<tr><td><b>상대강도</b></td><td class="mono">{w['rs']}</td>
    <td>QQQ 대비 63일 초과수익</td>
    <td class="small muted wrap">지수를 못 이기는 종목은 지수를 사면 된다</td></tr>
<tr><td><b>리스크</b></td><td class="mono">{w['risk']}</td>
    <td>20일 변동성 6 · 120일 최대낙폭 4</td>
    <td class="small muted wrap">같은 수익이면 덜 흔들린 쪽</td></tr>
<tr><td><b>거시 적합성</b></td><td class="mono">{w['macro']}</td>
    <td>금리·리스크 국면 × 세그먼트 듀레이션/베타</td>
    <td class="small muted wrap">국면이 바뀌면 같은 종목도 점수가 바뀐다</td></tr>
</table></div>
<p class="small muted">신호 라벨 — <b class="up">CORE</b> {s['rules']['core_score']:.0f}점 이상 + 골든크로스 ·
<b>SATELLITE</b> 편입하되 조건 일부 미달 · <b class="down">EXIT</b> 12-1 모멘텀 음수 또는 200일선 이탈 ·
<b class="muted">WATCH</b> {s['rules']['min_score']:.0f}점 미만 관찰.</p>"""
    return card("4-Factor 채점 · 100점", body)


def sec_sizing(s: dict) -> str:
    z, r = s["sizing"], s["rules"]
    tiles = "".join([
        tile("풀 켈리", f'{z["full_kelly"]*100:.1f}%', "이론값 — 그대로 쓰지 않음"),
        tile(f'1/{z["divisor"]} 켈리', f'{z["fractional_kelly"]*100:.1f}%', "실제 적용"),
        tile("종목당 캡", f'{z["position_cap"]*100:.1f}%',
             "상·하한 절단" if z["clipped"] else "켈리값 그대로", "up"),
        tile("최대 그로스", f'{z["max_gross"]*100:.1f}%', f'캡 × {r["top_n"]}종목'),
    ])
    body = f"""
<p>포지션 크기가 이 전략의 <b>유일한 리스크 관리 수단</b>입니다 — 손절선이 아니라 사이즈로 관리합니다.
캡은 임의의 숫자가 아니라 켈리 기준에서 뽑습니다. 이기면 <b>+{z['win_payoff']:.0%}</b>,
지면 <b>−{z['loss_gap']:.0%}</b>(실적 갭 + 추세 붕괴), 승률 <b>{z['win_rate']:.0%}</b> 가정입니다.</p>
<div class="tiles">{tiles}</div>
<p class="mono small">f* = (p·b − q·l) / (b·l)
= ({z['win_rate']:.2f}×{z['win_payoff']:.2f} − {1 - z['win_rate']:.2f}×{z['loss_gap']:.2f})
÷ ({z['win_payoff']:.2f}×{z['loss_gap']:.2f})
= {z['full_kelly']:.3f} &nbsp;→&nbsp; 1/{z['divisor']} 켈리 = <b>{z['position_cap']:.1%}</b></p>
<p class="small muted">풀 켈리는 파산 확률을 감수하는 값이라 실무에서 쓰지 않습니다. 가정이 조금만 틀려도
과베팅이 되기 때문에 1/{z['divisor']}만 씁니다. 가정을 바꾸려면
<span class="mono">data/nasdaq-universe.json</span> 의 <span class="mono">kelly</span> 항목을 고치세요.</p>"""
    return card("포지션 사이징 · 켈리 기준", body)


def sec_jump(s: dict) -> str:
    r = s["rules"]
    cap_pct = r["position_cap"] * r["jump_cap_factor"]
    flagged = [x for x in s["rows"] if x["ok"] and x["jumps"] >= r["jump_cap_at"]]
    if flagged:
        items = "".join(
            f'<tr><td class="mono b">{_e(x["ticker"])}</td><td>{_e(x["name"])}</td>'
            f'<td class="mono">{x["jumps"]}회</td>'
            f'<td class="{"down" if x["excluded"] else "warn"}">'
            f'{"편입 제외" if x["excluded"] else f"비중 {cap_pct:.1%} 로 축소"}</td>'
            f'<td class="mono">{num(x["vol20"], 1, "%")}</td></tr>' for x in flagged)
        table = ('<div class="scroll"><table><tr><th>티커</th><th>이름</th><th>갭</th>'
                 f'<th>조치</th><th>20일 변동성</th></tr>{items}</table></div>')
    else:
        table = ('<p class="muted">현재 캡·제외 대상 없음 — 최근 '
                 f'{r["jump_window"]}거래일 내 ±{num(r["jump_threshold"], 0)}% 갭이 '
                 f'{r["jump_cap_at"]}회 이상인 종목이 없습니다.</p>')
    body = f"""
<p>바이오의 임상 발표처럼, 나스닥에는 <b>실적 발표 갭</b>이 있습니다. 모멘텀 점수는 높지만
사실상 이벤트 베팅인 종목을 걸러내기 위해 최근 {r['jump_window']}거래일 동안
<b>일간 ±{num(r['jump_threshold'], 0)}% 이상</b> 움직인 횟수를 셉니다.</p>
<ul>
<li><b>{r['jump_cap_at']}~{r['jump_exclude_at'] - 1}회</b> — 편입은 하되 비중을 캡의
    {r['jump_cap_factor']:.0%}({cap_pct:.1%})로 축소</li>
<li><b>{r['jump_exclude_at']}회 이상</b> — 점수와 무관하게 편입 제외(관찰만)</li>
</ul>
{table}"""
    return card("점프 리스크 필터", body)


def sec_top(s: dict) -> str:
    top, cash = s["top"], s["cash_pct"]
    r, z = s["rules"], s["sizing"]
    if not top:
        return card(f"Top-{r['top_n']} 포트폴리오",
                    '<p class="down">편입 종목 없음 — 전액 현금입니다. 점수·12-1 모멘텀·'
                    '200일선 조건을 모두 통과한 종목이 없습니다.</p>')
    rows = "".join(
        f'<tr><td class="mono">{x["pos"]}</td>'
        f'<td class="mono b">{_e(x["ticker"])}</td>'
        f'<td>{_e(x["name"])}<div class="small muted">{_e(x["segment"])}</div></td>'
        f'<td class="mono">{_e(x.get("archetype", "—"))}</td>'
        f'<td class="mono b">{num(x["total"], 1)}</td>'
        f'<td class="mono">{signed(x["m12_1"], 1)}</td>'
        f'<td class="mono">{signed(x["rs63"], 1)}</td>'
        f'<td class="mono">{signed(x["vs_sma200"], 1)}</td>'
        f'<td class="{SIGNAL_CLS.get(x["signal"], "")}">{_e(x["signal"])}</td>'
        f'<td class="mono b w">{x["weight"] * 100:.1f}%'
        f'{bar(x["weight"] / max(z["position_cap"], 0.01))}</td></tr>'
        for x in top)
    seg_sum: dict[str, float] = {}
    for x in top:
        seg_sum[x["segment"]] = seg_sum.get(x["segment"], 0.0) + x["weight"]
    segs = " · ".join(f'{_e(k)} {v:.1%}' for k, v in sorted(seg_sum.items(), key=lambda kv: -kv[1]))
    notes = ("<p class='small muted'>" + " · ".join(_e(n) for n in s["notes"]) + "</p>") if s["notes"] else ""
    exits = s.get("exits") or []
    exit_line = (f'<p class="small"><b class="down">EXIT</b> — {_e(", ".join(exits))}'
                 f'{" 외" if len(exits) >= 12 else ""} · 12-1 모멘텀 음수이거나 200일선 아래 — '
                 f'보유 중이면 청산 후보입니다.</p>') if exits else ""
    tiles = "".join([
        tile("모델 투자비중", f'{s["gross_pct"] * 100:.1f}%', f'현금 {cash * 100:.1f}%',
             "up" if s["gross_pct"] > 0.5 else "warn"),
        tile("종목당 캡", f'{z["position_cap"] * 100:.1f}%', f'1/{z["divisor"]} 켈리'),
        tile("편입", f'{len(top)}종목', f'서브테마당 최대 {r["max_per_segment"]}'),
        tile("레짐 배수", f'{s["regime"]["exposure"]:.0%}', _e(s["regime"]["regime"]),
             ACCENT.get(s["regime"]["regime"], "muted")),
    ])
    body = f"""
<p>점수 상위 종목에 <b>켈리 캡({z['position_cap']:.1%})을 기준선</b>으로 비중을 줍니다.
점수는 캡의 ±{r['score_tilt']:.0%}만 기울입니다 — 서열은 반영하되 1등에 몰지 않습니다.
서브테마당 최대 {r['max_per_segment']}종목, 점프 리스크 종목은 캡의 {r['jump_cap_factor']:.0%}.
그 위에 레짐 투자비중 <b>{s['regime']['exposure']:.0%}</b>를 곱하고, 남는 몫은 현금으로 둡니다.</p>
<div class="tiles">{tiles}</div>
<div class="scroll"><table class="top">
<tr><th>#</th><th>티커</th><th>이름 / 세그먼트</th><th>유형</th><th>점수</th>
<th>12-1M</th><th>RS 63D</th><th>vs 200MA</th><th>신호</th><th>비중</th></tr>
{rows}
<tr class="cash"><td colspan="9">현금 — 갭·급락 버퍼</td>
<td class="mono b">{cash * 100:.1f}%</td></tr>
</table></div>
<p class="small">세그먼트 배분: {segs}</p>
{exit_line}
{notes}"""
    return card(f"Top-{r['top_n']} 포트폴리오", body)


def sec_archetype(s: dict) -> str:
    arch, alloc = s.get("archetypes", {}), s.get("archetype_alloc", {})
    by_key: dict[str, list[str]] = {}
    for row in s["rows"]:
        if row["ok"]:
            by_key.setdefault(row.get("archetype", "—"), []).append(row["ticker"])
    rows = ""
    for k, v in arch.items():
        names = by_key.get(k, [])
        shown = ", ".join(names[:10]) + (" 외" if len(names) > 10 else "")
        rows += (f'<tr><td class="mono b">{_e(k)}</td>'
                 f'<td class="wrap">{_e(v.get("label", ""))}'
                 f'<div class="small muted">{_e(v.get("desc", ""))}</div></td>'
                 f'<td class="mono b">{alloc.get(k, 0) * 100:.1f}%</td>'
                 f'<td class="small muted wrap">{_e(shown)}</td>'
                 f'<td class="small down wrap">{_e(v.get("risk", ""))}</td></tr>')
    body = f"""
<p>같은 'AI 수혜주'라도 <b>AI를 어떻게 쓰는지</b>에 따라 리스크의 성격이 다릅니다.
점수는 가격에서 나오지만, 배분이 한 유형으로 쏠렸는지는 따로 봐야 합니다 —
특히 <b>D(AI-네이티브)</b>는 서사가 꺾이면 실적보다 멀티플이 먼저 무너집니다.</p>
<div class="scroll"><table>
<tr><th>유형</th><th class="wrap">정의</th><th>현재 배분</th><th class="wrap">유니버스 종목</th><th class="wrap">주 리스크</th></tr>
{rows}</table></div>"""
    return card("아키타입별 배분 · AI를 어떻게 쓰는가", body)


def sec_falsify(s: dict) -> str:
    f = s.get("falsification") or {}
    checks = f.get("checks", [])
    rows = "".join(
        f'<tr><td class="{"down b" if c["hit"] else "muted"}">'
        f'{"충족" if c["hit"] else "미충족"}</td>'
        f'<td>{_e(c["cond"])}</td><td class="mono small">{_e(c["detail"])}</td>'
        f'<td class="small muted wrap">{_e(c["impact"])}</td></tr>' for c in checks)
    hits = f.get("hits", 0)
    verdict = (f'<p class="verdict"><b class="down">반증 조건 {hits}개 충족</b> — '
               f'둘 이상이면 테마 배분을 절반으로 줄이는 구간입니다.</p>' if f.get("halve") else
               f'<p class="verdict"><b class="up">전제 유지</b> — 충족 {hits}개. '
               f'둘 이상 충족되면 배분을 절반으로 줄입니다.</p>')
    breadth = f.get("breadth")
    avg_mom = f.get("avg_mom")
    body = f"""
<p>전략이 틀렸다고 인정할 기준을 미리 적어 둡니다 — 사후에 이유를 붙이지 않기 위해서입니다.
현재 유니버스의 <b>{"—" if breadth is None else f"{breadth * 100:.0f}%"}</b>가 200일선 위에 있고,
평균 12-1 모멘텀은 <b>{"—" if avg_mom is None else f"{avg_mom:+.1f}%"}</b>입니다.</p>
<div class="scroll"><table>
<tr><th>상태</th><th class="wrap">반증 조건</th><th>현재</th><th class="wrap">충족 시 조치</th></tr>{rows}</table></div>
{verdict}"""
    return card("반증 조건 · 언제 이 전략을 접는가", body)


def sec_board(s: dict) -> str:
    rows = "".join(
        f'<tr class="{"dim" if not x["ok"] else ""}">'
        f'<td class="mono">{x["rank"]}</td>'
        f'<td class="mono b">{_e(x["ticker"])}</td>'
        f'<td>{_e(x["name"])}</td>'
        f'<td class="small muted">{_e(x["segment"])}</td>'
        f'<td class="mono">{_e(x.get("archetype", "—"))}</td>'
        f'<td class="{SIGNAL_CLS.get(x["signal"], "")}">{_e(x["signal"])}</td>'
        f'<td class="mono b">{num(x["total"], 1)}</td>'
        f'<td class="mono">{num(x["momentum"], 1)}</td>'
        f'<td class="mono">{num(x["trend"], 1)}</td>'
        f'<td class="mono">{num(x["rs"], 1)}</td>'
        f'<td class="mono">{num(x["risk"], 1)}</td>'
        f'<td class="mono">{num(x["macro"], 1)}</td>'
        f'<td class="mono">{signed(x["m12_1"], 1)}</td>'
        f'<td class="mono">{signed(x["off_high"], 1)}</td>'
        f'<td class="mono">{num(x["vol20"], 1, "%")}</td>'
        f'<td class="{"down" if x["excluded"] else "warn" if x["capped"] else "muted"}">'
        f'{_e(x["jump_risk"])}</td>'
        f'<td class="small muted wrap">{_e(" · ".join(x["flags"]))}</td></tr>'
        for x in s["rows"])
    body = f"""
<p class="muted small">열 제목을 누르면 정렬됩니다. 점수는 유니버스 {s['scored_count']}종
횡단면 백분위 기준이라, 같은 종목이라도 다른 날에는 다른 점수가 나옵니다.</p>
<div class="scroll"><table class="board sortable">
<tr><th>#</th><th>티커</th><th>이름</th><th>세그먼트</th><th>유형</th><th>신호</th><th>총점</th>
<th>모멘텀40</th><th>추세25</th><th>RS15</th><th>리스크10</th><th>거시10</th>
<th>12-1M</th><th>고점대비</th><th>변동성</th><th>갭</th><th>플래그</th></tr>
{rows}</table></div>"""
    return card("전체 유니버스 스코어보드", body)


def sec_method(s: dict) -> str:
    body = f"""
<ul>
<li><b>데이터</b> — Yahoo Finance 일별 종가 2년치(yfinance). 결과는 <b>{s['cache_ttl_hours']}시간 캐시</b>되고,
    새로고침 버튼은 캐시를 무시하고 다시 계산합니다.</li>
<li><b>리밸런싱</b> — 점수는 조회 시점 기준입니다. 실제 운용에서는 주 1회(금요일 종가) 리밸런싱을 가정합니다.</li>
<li><b>레짐 우선</b> — 종목 점수가 아무리 높아도 레짐이 Risk-Off면 총 투자비중은 25%입니다.
    방어가 선택보다 먼저입니다.</li>
<li><b>사이즈가 리스크 관리</b> — 손절선을 쓰지 않습니다. 켈리 캡 {s['sizing']['position_cap']:.1%}와
    현금 비중이 갭을 견디는 장치입니다.</li>
<li><b>한계</b> — 모멘텀 전략은 추세 전환 구간(급반전)에서 가장 취약합니다. 이 페이지는 백테스트가 아니라
    <b>현재 상태 스냅샷</b>이며, 수수료·슬리피지·세금은 반영되어 있지 않습니다.</li>
<li><b>knot.e 원칙</b> — 이 페이지는 <b>제안</b>이고 결정은 사람이 합니다. 투자 자문이 아닙니다.</li>
</ul>"""
    return card("방법론 · 데이터 · 한계", body)


# ─────────────────────── 문서 ───────────────────────
def render_page(s: dict, live: bool = True) -> str:
    banner = ""
    if s.get("demo"):
        banner += ('<div class="banner warn">데모 모드 — 합성 가격으로 그린 레이아웃 확인용입니다. '
                   '표시된 수치는 실제 시장 데이터가 아닙니다.</div>')
    if s.get("warnings"):
        banner += '<div class="banner down">' + "<br>".join(_e(w) for w in s["warnings"]) + "</div>"
    refresh = ('<button id="rf">새로고침</button>' if live
               else '<span class="small muted">정적 스냅샷</span>')
    stamp = f'{_e(s["generated_at"])} · ' + ("캐시" if s.get("from_cache") else "실시간 갱신")

    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AMQS-NDX · 나스닥 4-Factor 모멘텀</title>
<style>{CSS}</style></head><body>
<main>
<header>
  <h1>AMQS-NDX</h1>
  <p class="lead">미국 나스닥 대형·성장 {s['universe_count']}종 · QQQ/SPY 레짐 · 4-Factor 모멘텀 ·
  점프 리스크 필터 · 켈리 캡 Top-{s['rules']['top_n']} 비중. Yahoo · {s['cache_ttl_hours']}시간 캐시.</p>
  <div class="stamp"><span class="small muted">{stamp}</span>{refresh}</div>
</header>
{banner}
{sec_regime(s)}
{sec_macro(s)}
{sec_factors(s)}
{sec_sizing(s)}
{sec_jump(s)}
{sec_top(s)}
{sec_archetype(s)}
{sec_falsify(s)}
{sec_board(s)}
{sec_method(s)}
<footer class="small muted">knot.e · AMQS-NDX — 정보 제공 목적입니다. 투자 판단과 책임은 본인에게 있습니다.</footer>
</main>
<script>{JS}</script>
</body></html>"""


CSS = """
:root{--bg:#080b0f;--card:#111820;--line:#1e2833;--fg:#e8edf3;--muted:#8a97a6;
--up:#4ade80;--down:#f87171;--warn:#fbbf24;--mono:ui-monospace,SFMono-Regular,"SF Mono",Menlo,monospace}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font-family:-apple-system,BlinkMacSystemFont,"Pretendard","Apple SD Gothic Neo","Malgun Gothic",system-ui,sans-serif;
line-height:1.7;-webkit-font-smoothing:antialiased}
main{max-width:1180px;margin:0 auto;padding:48px 20px 72px}
header{margin-bottom:28px}
h1{font-size:clamp(38px,7vw,64px);letter-spacing:-.04em;margin:0 0 12px;font-weight:800}
.lead{color:var(--muted);max-width:780px;margin:0 0 20px;font-size:15px}
.stamp{display:flex;align-items:center;gap:14px;flex-wrap:wrap}
button{background:#1a2430;color:var(--fg);border:1px solid var(--line);border-radius:8px;
padding:8px 16px;font:inherit;font-size:14px;cursor:pointer}
button:hover{background:#22303f}
.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:24px;margin:18px 0}
.card h2{font-size:19px;margin:0 0 12px;letter-spacing:-.01em}
.card p{font-size:15px}
.card ul{font-size:15px;padding-left:20px}.card li{margin:6px 0}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin:18px 0}
.tile{background:#0d141b;border:1px solid var(--line);border-radius:12px;padding:16px;text-align:center}
.tile-l{color:var(--muted);font-size:13px}
.tile-v{font-family:var(--mono);font-size:26px;font-weight:700;margin:6px 0 2px;letter-spacing:-.02em}
.tile-s{color:var(--muted);font-size:12px}
.verdict{border-left:3px solid var(--line);padding-left:14px}
.up{color:var(--up)}.down{color:var(--down)}.warn{color:var(--warn)}.muted{color:var(--muted)}
.mono{font-family:var(--mono)}.b{font-weight:700}.small{font-size:13px}
.scroll{overflow-x:auto;margin:14px -4px 0;padding:0 4px}
table{border-collapse:collapse;width:100%;font-size:14px;white-space:nowrap}
th{text-align:left;color:var(--muted);font-weight:600;font-size:13px;
border-bottom:1px solid var(--line);padding:8px 10px}
td{padding:8px 10px;border-bottom:1px solid #161e28;vertical-align:top}
tr:last-child td{border-bottom:none}
table.mini{max-width:660px}
table.sortable th{cursor:pointer;user-select:none}
table.sortable th:hover{color:var(--fg)}
tr.dim td{opacity:.45}
tr.cash td{color:var(--muted);border-top:1px solid var(--line)}
td.w{min-width:112px}
td.wrap,th.wrap{white-space:normal;min-width:200px}
.bar{height:4px;background:#1b242f;border-radius:3px;margin-top:5px;overflow:hidden}
.bar span{display:block;height:100%;background:linear-gradient(90deg,#2dd4bf,#4ade80)}
.banner{border-radius:10px;padding:12px 16px;margin:14px 0;font-size:14px;
border:1px solid var(--line);background:#131a22}
.banner.warn{border-color:#4a3a10;background:#1c1608;color:var(--warn)}
.banner.down{border-color:#4a1f1f;background:#1c0f0f;color:var(--down)}
footer{margin-top:32px;text-align:center}
@media(max-width:640px){main{padding:32px 14px 56px}.card{padding:18px 14px}}
"""

JS = """
(function(){
  var rf=document.getElementById('rf');
  if(rf) rf.addEventListener('click',function(){
    rf.disabled=true; rf.textContent='갱신 중…';
    location.href = location.pathname + '?refresh=1';
  });
  document.querySelectorAll('table.sortable').forEach(function(t){
    var head=t.rows[0];
    Array.prototype.forEach.call(head.cells,function(th,i){
      th.addEventListener('click',function(){
        var rows=Array.prototype.slice.call(t.rows,1);
        var dir=th.dataset.dir==='asc'?-1:1; th.dataset.dir=dir===1?'asc':'desc';
        rows.sort(function(a,b){
          var x=a.cells[i].innerText.replace(/[,%+]/g,''), y=b.cells[i].innerText.replace(/[,%+]/g,'');
          var nx=parseFloat(x), ny=parseFloat(y);
          if(!isNaN(nx)&&!isNaN(ny)) return (nx-ny)*dir;
          return x.localeCompare(y,'ko')*dir;
        });
        rows.forEach(function(r){t.tBodies[0].appendChild(r)});
      });
    });
  });
})();
"""
