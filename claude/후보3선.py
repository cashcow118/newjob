#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
후보3선.py — 매일 14:00 「오늘의 후보 3선」 (투자지침 v2 / 프롬프트_종목발굴3선_2026-09-11)

  ① scan_signals.py 실행(또는 기존 scan_res.csv 재사용)
  ② 4개 기준(낙폭과대·짝궁·외국인 수급·거래량 증가)으로 후보 풀 구성
  ③ 지침 우선순위대로 정확히 3개 선발 → 보고서 + 텔레그램 전송

사용:
  python 후보3선.py                 # 스캔 실행 후 선발 (기본)
  python 후보3선.py --no-scan       # 기존 scan_res.csv 재사용 (빠름)
  python 후보3선.py --no-telegram   # 전송 없이 화면·파일만
  python 후보3선.py --date 2026-09-18

같은 폴더에 필요한 것:
  scan_signals.py, kospi100.csv          (기존 파이프라인)
  config.json                            (T·슬롯·한도·텔레그램 토큰)
  holdings.csv    (Code,Name)            보유 종목 = 제외 대상
  foreign.csv     (Code,Name,NetBuy,Days5)  HTS [0266] 캡처를 옮겨 적은 것. 없으면 ③은 "확인 필요"
  sector.csv      (Code,Sector)          선택. 없으면 같은 업종 2개 제한 미적용
  holidays_kr.csv (Date)                 선택. 없으면 D+10은 휴장일 미반영

이 스크립트는 추정치로 후보를 만들지 않는다. 값을 구할 수 없으면 "확인 필요"로 남긴다.
"""
import os
import sys
import csv
import json
import time
import argparse
import subprocess
import datetime as dt

HERE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable

SEMI_CODES = {"005930", "000660"}          # 확실한 반도체 대형주(지수 주도). 그 외는 sector.csv로 판정
SAMSUNG, HYNIX = "005930", "000660"
PAIR_GAP = 0.03                             # 짝궁 신호 임계 +3%p
D_VOL = 1.5                                 # 전략 D 거래량 배수
WATCH_LO, WATCH_HI = -0.20, -0.15           # 워치리스트 구간
VOL_SPIKE = 2.0                             # 기준 ④ 거래량 배수
SPIKE_RET_LO, SPIKE_RET_HI = -0.10, 0.10    # 기준 ④ 등락 범위
EXCLUDE_RET = 0.15                          # 당일 +15% 이상 급등 제외


# ────────────────────────────────── 입출력 ──────────────────────────────────
def kst_now():
    return dt.datetime.utcnow() + dt.timedelta(hours=9)


def read_csv_rows(fname):
    p = os.path.join(HERE, fname)
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def load_config():
    p = os.path.join(HERE, "config.json")
    cfg = {
        "T": None, "slot_pct": 0.25, "pair_pct": 0.15, "empty_slots": None,
        "discretion_A": None, "discretion_B": None, "semi_weight_pct": None,
        "event_dday": None, "limit_state": "normal",
        "telegram_token": "", "telegram_chat_id": "",
    }
    if os.path.exists(p):
        with open(p, encoding="utf-8") as f:
            cfg.update(json.load(f))
    return cfg


def f(row, key, default=None):
    """CSV 문자열 → float. 빈 값·파싱 실패는 default."""
    try:
        v = row.get(key)
        return default if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return default


def b(row, key):
    return str(row.get(key, "")).strip().lower() in ("true", "1", "yes")


# ────────────────────────────────── 스캔 ──────────────────────────────────
def scan_fail_count():
    """scan_signals.json의 fails 개수 — 없으면 0."""
    p = os.path.join(HERE, "scan_signals.json")
    if not os.path.exists(p):
        return 0
    try:
        with open(p, encoding="utf-8") as fh:
            return len(json.load(fh).get("fails") or [])
    except Exception:
        return 0


def run_scan(date_arg):
    print("[1/4] 100종목 스캔 실행 중… (2~6분)")
    cmd = [PY, os.path.join(HERE, "scan_signals.py")]
    if date_arg:
        cmd.append(date_arg)
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print("  [경고] 스캔 실패:", (r.stderr or r.stdout)[-400:])
        return False
    return True


# ─────────────────────────── 보조 데이터 (필요 거래량 등) ───────────────────────────
_bar_cache = {}


def bars(code):
    """FDR 일봉. 거래량·20일 평균 거래량을 얻기 위해 후보군에만 호출한다."""
    if code in _bar_cache:
        return _bar_cache[code]
    try:
        import pandas as pd
        import FinanceDataReader as fdr
        end = kst_now().date()
        start = end - dt.timedelta(days=130)
        df = fdr.DataReader(code, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
        df = df[df["Volume"] > 0]
        _bar_cache[code] = df if len(df) >= 25 else None
    except Exception:
        _bar_cache[code] = None
    time.sleep(0.05)
    return _bar_cache[code]


def volume_facts(code):
    """(당일 거래량, 20일 평균 거래량) — 못 구하면 (None, None)."""
    df = bars(code)
    if df is None:
        return None, None
    try:
        return float(df["Volume"].iloc[-1]), float(df["Volume"].iloc[-21:-1].mean())
    except Exception:
        return None, None


# ────────────────────────────────── 날짜 ──────────────────────────────────
def load_holidays():
    rows = read_csv_rows("holidays_kr.csv")
    if not rows:
        return None
    out = set()
    for r in rows:
        v = (r.get("Date") or "").strip()
        if v:
            out.add(v)
    return out or None


def d_plus_10(base, holidays):
    """10 거래일 뒤. holidays_kr.csv가 없으면 주말만 반영(휴장일 미반영)."""
    d, n = base, 0
    while n < 10:
        d += dt.timedelta(days=1)
        if d.weekday() >= 5:
            continue
        if holidays and d.strftime("%Y-%m-%d") in holidays:
            continue
        n += 1
    return d


# ────────────────────────────────── 선발 ──────────────────────────────────
def build_pool(rows, holdings, foreign, sectors):
    """제외 규칙 적용 후, 종목별로 해당되는 기준(①②③④)을 표시한다."""
    pool = {}
    for r in rows:
        code = (r.get("code") or "").strip().zfill(6)
        name = (r.get("name") or "").strip()
        if not code or not name:
            continue
        if code in holdings:
            continue                                    # 보유 종목 = 물타기 금지
        if name.endswith(("우", "우B", "우C")) or any(
                k in name for k in ("스팩", "ETF", "ETN", "리츠")):
            continue
        dd60, ret, vr = f(r, "dd60"), f(r, "ret"), f(r, "vol_ratio")
        if dd60 is None or ret is None or vr is None:
            continue
        if ret >= EXCLUDE_RET:
            continue                                    # 당일 +15% 이상 급등 제외
        first20 = b(r, "first_touch20")
        if dd60 <= -0.20 and not first20:
            continue                                    # 첫 도달이 아닌 −20% 이하 제외

        e = {
            "code": code, "name": name, "close": f(r, "close"), "ret": ret,
            "dd60": dd60, "vol_ratio": vr, "hi60": f(r, "hi60"),
            "first20": first20, "first25": b(r, "first_touch25"),
            "sector": sectors.get(code) if sectors else None,
            "c1_signal": False, "c1_watch": False, "c2_pair": False,
            "c3_foreign": foreign.get(code) if foreign else None,
            "c4_volume": False,
        }
        if first20 and vr >= D_VOL:
            e["c1_signal"] = True                       # ① 전략 D 신호 확정
        if WATCH_LO < dd60 <= WATCH_HI:
            e["c1_watch"] = True                        # ① 워치리스트(조건부)
        if vr >= VOL_SPIKE and SPIKE_RET_LO <= ret <= SPIKE_RET_HI:
            e["c4_volume"] = True                       # ④ 거래량 증가
        pool[code] = e
    return pool


def pair_gap(rows):
    """삼성전자 등락률 − SK하이닉스 등락률. 신호가 없어도 값을 적는다."""
    m = {(r.get("code") or "").strip().zfill(6): f(r, "ret") for r in rows}
    s, h = m.get(SAMSUNG), m.get(HYNIX)
    if s is None or h is None:
        return None
    return s - h


def is_semi(e):
    if e["code"] in SEMI_CODES:
        return True
    return bool(e["sector"] and "반도체" in e["sector"])


def rank_key(e):
    """동순위 정렬: (1) 반도체·지수 주도 대형주 (2) 거래량 배수 큰 순 (3) 낙폭 깊은 순."""
    return (0 if is_semi(e) else 1, -e["vol_ratio"], e["dd60"])


def pick3(pool, gap, sectors):
    t1 = [e for e in pool.values() if e["c1_signal"] or e["c2_pair"]]
    t2 = [e for e in pool.values()
          if e not in t1 and e["c1_watch"] and (e["c3_foreign"] or e["c4_volume"])]
    t3 = [e for e in pool.values()
          if e not in t1 and e not in t2 and (e["c3_foreign"] or e["c4_volume"])]
    # 3순위 안에서는 두 기준(③·④)이 겹치는 종목을 먼저
    t3.sort(key=lambda e: (0 if (e["c3_foreign"] and e["c4_volume"]) else 1, *rank_key(e)))
    t1.sort(key=rank_key)
    t2.sort(key=rank_key)

    picked, sector_count, in_rule = [], {}, len(t1) + len(t2)
    for tier, label in ((t1, "[신호·실행가능]"), (t2, "[워치·조건부]"), (t3, "[관찰·규칙 밖]")):
        if label == "[관찰·규칙 밖]" and in_rule >= 3:
            break                                       # 규칙 내 신호가 3개 이상이면 관찰 제외
        for e in tier:
            if len(picked) >= 3:
                break
            sec = e["sector"]
            if sectors and sec and sector_count.get(sec, 0) >= 2:
                continue                                # 같은 업종 최대 2개
            e["label"] = label
            picked.append(e)
            if sec:
                sector_count[sec] = sector_count.get(sec, 0) + 1
        if len(picked) >= 3:
            break
    return picked, len(t1), len(t2), len(t3)


# ────────────────────────────────── 보고서 ──────────────────────────────────
def pct(x, digits=1):
    return "확인 필요" if x is None else f"{x * 100:+.{digits}f}%"


def won(x):
    return "확인 필요" if x is None else f"{x:,.0f}"


def trigger_text(e):
    """[워치·조건부]·[관찰·규칙 밖]의 '규칙 신호로 바뀌는 조건' — 숫자로."""
    if e["label"] == "[신호·실행가능]":
        return "—"
    if not e["hi60"] or not e["close"]:
        return "확인 필요"
    line20 = e["hi60"] * 0.80
    need_drop = abs(line20 / e["close"] - 1) * 100
    vol_today, vol20 = volume_facts(e["code"])
    need_vol = f"{vol20 * D_VOL:,.0f}주" if vol20 else "확인 필요"
    return (f"종가 ≤ {line20:,.0f}원(추가 {need_drop:.1f}% 하락 필요) & 거래량 ≥ {need_vol}")


def exec_table(picked, cfg, holidays, today):
    rows = []
    T, slot_pct, pair_pct = cfg["T"], cfg["slot_pct"], cfg["pair_pct"]
    half = cfg.get("event_dday") is True or cfg.get("limit_state") == "half"
    for e in picked:
        if e["label"] != "[신호·실행가능]":
            continue
        if cfg.get("limit_state") == "stop":
            rows.append(f"- **{e['name']}** — 월 −8% 한도 도달 상태입니다. 실행표 대신 규칙을 상기합니다: "
                        f"그 달 신규 진입 중단, 보유분은 각 전략 청산 규칙대로만 정리.")
            continue
        strat = "P(짝궁)" if e["c2_pair"] else "D(낙폭과대 스윙)"
        base_pct = pair_pct if e["c2_pair"] else slot_pct
        if half:
            base_pct /= 2
        amount = T * base_pct if T else None
        qty = int(amount // e["close"]) if (amount and e["close"]) else None
        tp = e["close"] * 1.05 if e["close"] else None
        exit_line = ("익일 종가 전량 청산(장중 −3% 시 즉시)" if e["c2_pair"]
                     else f"D+10 {d_plus_10(today, holidays):%Y-%m-%d} 종가 무조건 청산")
        rows.append(
            f"- **{e['name']}({e['code']})** · 전략 {strat}"
            + (f" · 사이즈 {base_pct * 100:.0f}%" + (" (절반 적용)" if half else ""))
            + f" = {won(amount)}원 · 수량 {qty if qty is not None else '확인 필요'}주\n"
            f"  - 지정가 {won(e['close'])}원(종가 근처) · 주문 시각 **14:30~15:20**\n"
            + (f"  - +5% 절반 익절 지정가 **{won(tp)}원** (보유량 50%)\n" if not e["c2_pair"] else "")
            + f"  - 청산: {exit_line}"
        )
    return rows


def build_report(picked, cfg, meta, gap, counts, holidays, today):
    L = []
    src = meta["source"]
    L.append(f"# 오늘의 후보 3선 — {meta['now']:%Y-%m-%d %H:%M} KST")
    L.append("")
    L.append(f"- **원천·시각·잠정 여부**: {src} / 마지막 봉 {meta['last_bar']} / "
             f"{'**잠정(장중)**' if meta['partial'] else '확정'} / 스캔 N={meta['n']}"
             + (f" / 실패 {meta['fails']}종목" if meta["fails"] else ""))
    L.append(f"- **외국인 수급 원천**: {meta['foreign_src']}")
    L.append(f"- **재량 카운트**: A {cfg['discretion_A'] if cfg['discretion_A'] is not None else '확인 필요'}"
             f" · B {cfg['discretion_B'] if cfg['discretion_B'] is not None else '확인 필요'}")
    L.append(f"- **T 빈 슬롯**: {cfg['empty_slots'] if cfg['empty_slots'] is not None else '확인 필요'}")
    L.append(f"- **반도체 섹터 합산 비중(코어 포함, A 전체 대비)**: "
             f"{cfg['semi_weight_pct'] if cfg['semi_weight_pct'] is not None else '확인 필요'}")
    L.append(f"- **오늘 밤 이벤트 D-day**: "
             f"{'예 — 사이즈 절반' if cfg.get('event_dday') is True else ('아니오' if cfg.get('event_dday') is False else '확인 필요')}")
    L.append(f"- **짝궁 격차(삼성전자 − SK하이닉스)**: "
             f"{pct(gap, 2) if gap is not None else '확인 필요'}"
             f"{' → SK하이닉스 신호' if (gap is not None and gap >= PAIR_GAP) else ' → 신호 없음'}")
    L.append(f"- **후보 풀**: 1순위 {counts[0]} / 2순위 {counts[1]} / 3순위 {counts[2]}")
    if meta["sector_missing"]:
        L.append("- ⚠ sector.csv 없음 → **같은 업종 최대 2개 제한 미적용**(확인 필요)")
    if not holidays:
        L.append("- ⚠ holidays_kr.csv 없음 → D+10은 주말만 반영, **휴장일이 끼면 그만큼 순연**")
    L.append("")

    L.append("| 순위 | 종목(코드) | 라벨 | 현재가 | 60일 낙폭 | 거래량 배수 | 외국인 순매수(잠정) | 당일 등락 | 원인 1줄 · 거부권 | 규칙 신호 전환 조건 | 실행 |")
    L.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for i, e in enumerate(picked, 1):
        fo = e["c3_foreign"]
        fo_txt = (f"{fo['netbuy']} ({fo['days5']}/5일)" if fo else "확인 필요")
        L.append(
            f"| {i} | **{e['name']}({e['code']})** | {e['label']} | {won(e['close'])} | "
            f"{pct(e['dd60'])} | {e['vol_ratio']:.2f}배 | {fo_txt} | {pct(e['ret'], 2)} | "
            f"확인 필요 · 거부권 미점검 | {trigger_text(e)} | "
            f"{'실행표 ↓' if e['label'] == '[신호·실행가능]' else ('조건 충족 시' if e['label'] == '[워치·조건부]' else '없음')} |"
        )
    if len(picked) < 3:
        L.append("")
        L.append(f"⚠ **{len(picked)}개만 채웠습니다.** 규칙상 3개를 채워야 하지만 제외 규칙 통과 종목이 부족합니다. "
                 "HTS [0266]·[0173] 캡처를 주시면 ③·④ 기준으로 나머지를 채웁니다.")
    L.append("")

    ex = exec_table(picked, cfg, holidays, today)
    L.append("## 실행표 — [신호·실행가능] 종목만")
    L.extend(ex if ex else ["- 해당 없음(실행 가능 신호 0건). 오늘은 신규 진입 없음."])
    L.append("")

    L.append("## 리스크 3줄")
    L.append("1. 14:00 봉은 **잠정치**입니다. 종가 확정은 15:30이고, 경계 종목은 15:20 전에 다시 봐야 합니다.")
    L.append("2. 거부권(DART 공시·뉴스)이 이 표에 반영되어 있지 않습니다 — 구조적 악재가 있으면 건너뜁니다.")
    L.append("3. [관찰·규칙 밖] 종목은 백테스트 근거가 없습니다. 실행하면 재량 카운트이고 사이즈는 절반 슬롯 이하입니다.")
    L.append("")
    L.append("## 역검토 3줄 — 이 후보가 틀리는 경로")
    L.append("1. **−20% 첫 도달이 바닥이 아닐 때**: 구조적 악재로 내려온 낙폭은 D+10까지 더 깊어질 수 있습니다. 백테스트 최악 트레이드는 −35.7%였습니다.")
    L.append("2. **거래량 배수가 매도 폭발일 때**: 배수 2배는 관심 증가일 수도, 기관 이탈일 수도 있습니다. 수급 방향은 외국인 캡처 없이는 구분되지 않습니다.")
    L.append("3. **잠정 봉이 뒤집힐 때**: 14:00 기준 낙폭·거래량이 종가에 −20% 위로 회복하면 신호 자체가 사라집니다.")
    L.append("")
    L.append("*이 보고서는 근거를 모아줄 뿐 판단을 대신하지 않는다. 값을 구하지 못한 칸은 추정하지 않고 \"확인 필요\"로 남겼다.*")
    return "\n".join(L)


# ────────────────────────────────── 텔레그램 ──────────────────────────────────
def send_telegram(text, token, chat_id):
    if not token or not chat_id:
        print("  [알림] 텔레그램 토큰·챗ID가 config.json에 없습니다 — 전송 생략.")
        return False
    import requests
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    ok = True
    for i in range(0, len(text), 3800):
        chunk = text[i:i + 3800]
        try:
            r = requests.post(url, data={"chat_id": chat_id, "text": chunk,
                                         "disable_web_page_preview": True}, timeout=30)
            if r.status_code != 200:
                print(f"  [경고] 텔레그램 {r.status_code}: {r.text[:200]}")
                ok = False
        except Exception as e:
            print(f"  [경고] 텔레그램 전송 실패: {type(e).__name__} {e}")
            ok = False
        time.sleep(0.4)
    return ok


# ────────────────────────────────── 메인 ──────────────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-scan", action="store_true", help="스캔 생략, 기존 scan_res.csv 재사용")
    ap.add_argument("--no-telegram", action="store_true", help="전송 없이 화면·파일만")
    ap.add_argument("--date", help="기준일 YYYY-MM-DD (스캔에 전달)")
    a = ap.parse_args()

    now = kst_now()
    cfg = load_config()

    scanned = True if a.no_scan else run_scan(a.date)
    rows = read_csv_rows("scan_res.csv")
    if not rows:
        msg = ("후보 3선 실패 — scan_res.csv가 없습니다. 스캔이 실패했거나 아직 돌지 않았습니다. "
               "추정치로 후보를 만들지 않습니다.")
        print(msg)
        if not a.no_telegram:
            send_telegram(f"⚠ {now:%Y-%m-%d %H:%M} {msg}", cfg["telegram_token"], cfg["telegram_chat_id"])
        sys.exit(1)

    print("[2/4] 제외 규칙 적용 + 4개 기준 판정")
    holdings = {(r.get("Code") or "").strip().zfill(6) for r in (read_csv_rows("holdings.csv") or [])}
    sec_rows = read_csv_rows("sector.csv")
    sectors = {(r.get("Code") or "").strip().zfill(6): (r.get("Sector") or "").strip()
               for r in sec_rows} if sec_rows else None
    fo_rows = read_csv_rows("foreign.csv")
    foreign = {(r.get("Code") or "").strip().zfill(6):
               {"netbuy": (r.get("NetBuy") or "").strip(), "days5": (r.get("Days5") or "?").strip()}
               for r in fo_rows} if fo_rows else None
    holidays = load_holidays()

    pool = build_pool(rows, holdings, foreign, sectors)
    gap = pair_gap(rows)
    if gap is not None and gap >= PAIR_GAP and HYNIX in pool:
        pool[HYNIX]["c2_pair"] = True                   # ② 짝궁: 역방향은 후보가 아니다

    print("[3/4] 지침 우선순위대로 3개 선발")
    picked, n1, n2, n3 = pick3(pool, gap, sectors)

    meta = {
        "now": now,
        "source": ("scan_res.csv (FDR 일봉, PC 파이프라인)" if scanned
                   else "scan_res.csv (이전 실행 결과 재사용 — 스캔 실패)"),
        "last_bar": rows[0].get("last_bar", "확인 필요"),
        "partial": any(b(r, "partial") for r in rows),
        "n": len(rows),
        "fails": scan_fail_count(),
        "foreign_src": ("foreign.csv (HTS [0266] 장중매매현황 추정, 당일 잠정)"
                        if foreign else "**확인 필요** — HTS [0266] 외국인 순매수 상위 캡처를 주세요"),
        "sector_missing": sectors is None,
    }
    report = build_report(picked, cfg, meta, gap, (n1, n2, n3), holidays, now.date())

    os.makedirs(os.path.join(HERE, "reports"), exist_ok=True)
    rp = os.path.join(HERE, "reports", f"후보3선_{now:%Y-%m-%d}.md")
    with open(rp, "w", encoding="utf-8") as fh:
        fh.write(report)
    print(f"[4/4] 저장: {rp}\n")
    print(report)

    if not a.no_telegram:
        if send_telegram(report, cfg["telegram_token"], cfg["telegram_chat_id"]):
            print("\n텔레그램 전송 완료.")


if __name__ == "__main__":
    main()
