import os
import re
import json
import requests
import datetime
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

BOT_TOKEN  = os.environ.get("BOT_TOKEN", "")
CLAUDE_KEY = os.environ.get("CLAUDE_API_KEY", "")
BOT_PW     = os.environ.get("BOT_PASSWORD", "hanwha1234")
FB_URL     = "https://team-dashboard-c0d7b-default-rtdb.asia-southeast1.firebasedatabase.app"

AUTHED = set()

# ── Firebase ──────────────────────────────────────────────────
def fb_read(path):
    try:
        res = requests.get(f"{FB_URL}/{path}.json", timeout=5)
        return res.json() or {}
    except:
        return {}

def fb_write(path, data):
    try:
        res = requests.patch(f"{FB_URL}/{path}.json", json=data, timeout=5)
        return res.status_code == 200
    except:
        return False

def fb_push(path, data):
    try:
        requests.post(f"{FB_URL}/{path}.json", json=data, timeout=5)
    except:
        pass

# ── Claude API ────────────────────────────────────────────────
def ask_claude(messages, system="", max_tokens=1000):
    if not CLAUDE_KEY:
        return "AI 기능 준비 중"
    try:
        body = {"model": "claude-haiku-4-5", "max_tokens": max_tokens, "messages": messages}
        if system:
            body["system"] = system
        res = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": CLAUDE_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json=body, timeout=30,
        )
        data = res.json()
        if "content" not in data:
            return f"오류: {data.get('error',{}).get('message','API 오류')}"
        return data["content"][0]["text"]
    except Exception as e:
        return f"오류: {str(e)}"

# ── 자연어 → 재무 데이터 파싱 ────────────────────────────────
PARSE_SYSTEM = """당신은 재무 데이터 파싱 전문가입니다.
사용자의 자연어 입력에서 재무 수치를 추출하여 JSON으로만 반환하세요.

규칙:
- stmt: "pl" (P&L), "bs" (B/S), "cf" (C/F) 중 하나
- year: 연도 숫자 (예: 2026)
- month: 월 숫자 (예: 3)
- data: 항목명과 수치 딕셔너리 (단위: $M 또는 억원이면 자동 변환)
- 억원으로 입력된 경우 1380으로 나눠서 $M으로 변환
- 음수는 그대로 표현

항목명 매핑:
P&L: 매출→rev, 매출원가→cogs, 매출총이익→gp, 판관비→sga, EBITDA→ebitda, 
     D&A→da, EBIT→ebit, 영업이익→ebit, 이자비용→int, 당기순이익→ni, 순이익→ni
B/S: 자산→ta, 부채→liab, 자본→equity, 현금→cash, 매출채권→ar
C/F: 영업→ocf, 투자→icf, 재무→ffcf, 기말현금→end_cash, CAPEX→capex

JSON 형식 (다른 텍스트 없이):
{"stmt":"pl","year":2026,"month":3,"data":{"rev":124.0,"ebit":-3.0}}"""

def parse_financial_input(text):
    """자연어 입력을 재무 데이터 JSON으로 파싱"""
    result = ask_claude(
        [{"role": "user", "content": text}],
        system=PARSE_SYSTEM,
        max_tokens=500
    )
    try:
        clean = result.replace("```json", "").replace("```", "").strip()
        return json.loads(clean)
    except:
        return None

# ── HWR 컨텍스트 ──────────────────────────────────────────────
def get_hwr_context():
    ppv = fb_read("ppv/summary")
    fin = fb_read("financial")
    ctx = """답변 규칙: 마크다운 금지, 이모지 최소화, 보고서 형태로 간결하게.

당신은 HWR(Hanwha Q CELLS USA/HEUH) 미국 개발 사업 담당자입니다.

[포트폴리오] 94개 프로젝트, PV 13,761 MWac, ESS 10,871 MW

['26년 매각 대상 $142M]
Boulder Solar 3: H확도 $40M NBO (Morrison)
Bonanza Peak: M확도 $50M NDA/티저 (Lydian)
Oberon II~IV: M확도 $20M
Taormina/Lavender: M확도 각 $10M
Gibson: L확도 $12M

[운영자산 유동화]
단기매각: TotalJV(Ob1A/Rayos/Ellis/Skysol) + HEUH(Laguna/Astoria)
현금유입 $150~182M, 차입금 제거 $275M, PL -$58~-90M

[Atlas Milestone] 달성률 25%, D-Day 임박

"""
    if ppv and ppv.get("totalRisked"):
        ctx += f"[PPV 현황] 총 Risked ${ppv.get('totalRisked')}M "
        by = ppv.get("byStage", {})
        ctx += f"(Late ${by.get('Late',0)}M / Mid ${by.get('Mid',0)}M / Early ${by.get('Early',0)}M)\n"

    if fin:
        ctx += "\n[재무 데이터 (Firebase)]\n"
        for stmt in ["pl", "bs", "cf"]:
            d = fin.get(stmt, {})
            if d:
                years = sorted(d.keys(), reverse=True)[:2]
                for y in years:
                    months = sorted(d[y].keys(), key=lambda x: int(x), reverse=True)[:3]
                    for m in months:
                        items = {k: v for k, v in d[y][m].items() if k != "updated_at"}
                        ctx += f"{stmt.upper()} {y}년 {m}월: {items}\n"
    return ctx

# ── 의도 파악 ──────────────────────────────────────────────────
def detect_intent(text):
    """입력 텍스트의 의도 파악"""
    t = text.lower()
    # 재무 업데이트 의도
    fin_keywords = ["업데이트", "입력", "저장", "올려", "넣어", "실적", "수치", "매출", "영업이익",
                    "순이익", "ebitda", "자산", "부채", "자본", "현금흐름", "capex", "월별"]
    if any(k in t for k in fin_keywords) and any(c.isdigit() for c in text):
        return "finance_update"
    return "question"

# ── 인증 ──────────────────────────────────────────────────────
def is_authed(uid): return uid in AUTHED

# ── 메뉴 ──────────────────────────────────────────────────────
async def show_menu(update):
    await update.message.reply_text(
        "HWR Dashboard Bot\n\n"
        "조회 명령어\n"
        "  /status    매각현황\n"
        "  /atlas     Atlas Milestone\n"
        "  /ppa       PPA 진척\n"
        "  /liquidity 운영자산 유동화\n"
        "  /strategy  전략 액션\n"
        "  /ppv       PPV 현황\n"
        "  /financial 재무 현황\n\n"
        "재무 데이터 업로드\n"
        "  자연어로 입력하면 자동 저장됩니다.\n"
        "  예) '26년 3월 실적: 매출 124, 영업이익 -3, 순이익 -8'\n"
        "  예) '2026년 3월 BS: 자산 450, 부채 320, 자본 130'\n\n"
        "자유롭게 질문하셔도 됩니다."
    )

# ── 핸들러 ────────────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if is_authed(update.effective_user.id): await show_menu(update)
    else: await update.message.reply_text("HWR Dashboard Bot입니다.\n비밀번호를 입력하세요.")

async def ppv_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authed(update.effective_user.id):
        await update.message.reply_text("비밀번호를 먼저 입력하세요. /start"); return
    data = fb_read("ppv")
    summary = data.get("summary", {})
    if not summary:
        await update.message.reply_text("PPV 데이터 없음\n대시보드에서 스냅샷을 찍어주세요."); return
    by = summary.get("byStage", {})
    updated = summary.get("updatedAt", "?")[:10]
    msg = (f"PPV 현황 ({updated} 기준)\n\n"
           f"총 Risked PPV  ${summary.get('totalRisked','?')}M\n"
           f"  Late   ${by.get('Late',0):.1f}M\n"
           f"  Mid    ${by.get('Mid',0):.1f}M\n"
           f"  Early  ${by.get('Early',0):.1f}M")
    events = data.get("events", {})
    if events:
        evts = sorted(events.values(), key=lambda x: x.get("ts",""), reverse=True)[:3]
        msg += "\n\n최근 변경\n"
        for e in evts:
            proj = f"{e.get('project')}  " if e.get("project") else ""
            msg += f"  {e.get('ts','?')[:10]}  {proj}{e.get('type','?')}: {e.get('desc','?')}\n"
    await update.message.reply_text(msg)

async def financial_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authed(update.effective_user.id):
        await update.message.reply_text("비밀번호를 먼저 입력하세요. /start"); return
    data = fb_read("financial")
    if not data:
        await update.message.reply_text("재무 데이터 없음\n자연어로 입력해주세요.\n예) '26년 3월 매출 124, 영업이익 -3'"); return
    msg = "재무 현황\n\n"
    labels = {"pl": "P&L", "bs": "B/S", "cf": "C/F"}
    for stmt, label in labels.items():
        d = data.get(stmt, {})
        if not d: continue
        years = sorted(d.keys(), reverse=True)[:1]
        for y in years:
            months = sorted(d[y].keys(), key=lambda x: int(x), reverse=True)[:3]
            msg += f"{label} ({y}년)\n"
            for m in months:
                items = "  ".join([f"{k} {v}" for k, v in d[y][m].items() if k != "updated_at"])
                msg += f"  {m}월  {items}\n"
            msg += "\n"
    await update.message.reply_text(msg)

async def status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authed(update.effective_user.id):
        await update.message.reply_text("비밀번호를 먼저 입력하세요. /start"); return
    await update.message.reply_text(
        "'26년 매각현황\n\n총 목표  $142M\n\n"
        "H확도\n  Boulder Solar 3  $40M  NBO 협의 중\n\n"
        "M확도\n  Bonanza Peak     $50M  NDA/티저\n"
        "  Oberon II        $5M\n  Oberon III       $10M\n"
        "  Oberon IV        $5M\n  Taormina         $10M\n"
        "  Lavender         $10M\n\nL확도\n  Gibson           $12M  준비 중"
    )

async def atlas_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authed(update.effective_user.id):
        await update.message.reply_text("비밀번호를 먼저 입력하세요. /start"); return
    await update.message.reply_text(
        "Atlas North 1st Milestone\n\n달성률  25%  (12개 항목)\n\n"
        "완료      2.12(f) CAP License\n"
        "진행 중   2.12(a) Tax/Insurance\n          2.12(c) PPA Amendment\n"
        "D-Day 임박  D+10 초과"
    )

async def liquidity_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authed(update.effective_user.id):
        await update.message.reply_text("비밀번호를 먼저 입력하세요. /start"); return
    await update.message.reply_text(
        "운영자산 유동화\n\n단기 매각 (6개)\n"
        "  TotalJV   Ob1A, Rayos, Ellis, Skysol\n  HEUH      Laguna, Astoria\n\n"
        "예상 현금유입   $150~182M\n차입금 제거     $275M\nPL 영향         -$58~-90M\n\n"
        "중장기 보유\n  Ho'Ohana (2029년까지)  Oberon 1B  Imeson"
    )

async def strategy_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authed(update.effective_user.id):
        await update.message.reply_text("비밀번호를 먼저 입력하세요. /start"); return
    await update.message.reply_text(
        "전략 액션 아이템\n\n"
        "1. 선제적 매각 프로세스 구체화   진행 중\n"
        "2. EPC Framework 확정           완료\n"
        "3. Value-up 방안 구체화         진행 중\n"
        "4. Legacy 자산 전략             진행 중\n"
        "5. BESS 성장 전략               진행 중\n"
        "6. ISO별 Local GR               진행 중\n\n"
        "이행률  14%  (1/7)"
    )

async def ppa_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authed(update.effective_user.id):
        await update.message.reply_text("비밀번호를 먼저 입력하세요. /start"); return
    await update.message.reply_text(
        "PPA 진척 현황\n\n총 18개 프로젝트\n\n"
        "BL 단계   Atlas 15\n"
        "RFP 진행  Harlem River, Taormina, Lavender, Gibson\n"
        "미착수    13개\n\n계약 완료  0건"
    )

# ── 파일/이미지 처리 ──────────────────────────────────────────
async def handle_file(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authed(update.effective_user.id):
        await update.message.reply_text("비밀번호를 먼저 입력하세요. /start"); return
    await update.message.reply_text("파일 분석 중...")

    if update.message.photo:
        import base64
        photo = update.message.photo[-1]
        file = await ctx.bot.get_file(photo.file_id)
        file_bytes = await file.download_as_bytearray()
        img_b64 = base64.b64encode(file_bytes).decode()

        caption = update.message.caption or "이 이미지에서 재무 데이터를 추출해주세요."
        result = ask_claude(
            [{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": img_b64}},
                {"type": "text", "text": caption + "\n\n재무 데이터가 있으면 JSON으로 추출해주세요. 없으면 내용을 설명해주세요."}
            ]}],
            max_tokens=1000
        )
        # JSON 파싱 시도
        parsed = None
        try:
            clean = result.replace("```json","").replace("```","").strip()
            parsed = json.loads(clean)
        except:
            pass

        if parsed and all(k in parsed for k in ["stmt","year","month","data"]):
            await save_financial(update, parsed)
        else:
            await update.message.reply_text(result)

# ── 재무 데이터 저장 공통 함수 ────────────────────────────────
async def save_financial(update, parsed):
    stmt  = parsed.get("stmt")
    year  = parsed.get("year", 2026)
    month = parsed.get("month")
    data  = parsed.get("data", {})

    if not all([stmt, month, data]):
        await update.message.reply_text("데이터 파싱 실패. 다시 입력해주세요."); return

    data["updated_at"] = datetime.datetime.now().isoformat()[:16]
    data["updated_by"] = update.effective_user.username or "telegram"

    if fb_write(f"financial/{stmt}/{year}/{month}", data):
        items = "\n".join([f"  {k}  {v}" for k, v in data.items() if k not in ("updated_at","updated_by")])
        stmt_label = {"pl":"P&L","bs":"B/S","cf":"C/F"}.get(stmt, stmt.upper())
        await update.message.reply_text(
            f"{stmt_label} {year}년 {month}월 저장 완료\n\n{items}\n\n"
            f"대시보드 재무 탭에서 확인하세요."
        )
    else:
        await update.message.reply_text("저장 실패. 다시 시도해주세요.")

# ── 메시지 핸들러 (핵심: 자연어 처리) ────────────────────────
async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid  = update.effective_user.id
    text = update.message.text.strip()

    # 인증
    if not is_authed(uid):
        if text == BOT_PW:
            AUTHED.add(uid)
            await update.message.reply_text("인증되었습니다.")
            await show_menu(update)
        else:
            await update.message.reply_text("비밀번호가 틀렸습니다. /start")
        return

    # 재무 업데이트 의도 감지
    intent = detect_intent(text)

    if intent == "finance_update":
        await update.message.reply_text("재무 데이터 파싱 중...")
        parsed = parse_financial_input(text)

        if parsed and all(k in parsed for k in ["stmt","year","month","data"]):
            # 확인 메시지 먼저 보여주기
            stmt_label = {"pl":"P&L","bs":"B/S","cf":"C/F"}.get(parsed.get("stmt"), "재무")
            preview = "\n".join([f"  {k}: {v}" for k,v in parsed.get("data",{}).items()])
            await update.message.reply_text(
                f"아래 내용으로 저장할까요?\n\n"
                f"{stmt_label}  {parsed.get('year')}년 {parsed.get('month')}월\n"
                f"{preview}\n\n저장하려면 '확인', 취소하려면 '취소'"
            )
            # 임시 저장
            ctx.user_data["pending_fin"] = parsed
        else:
            await update.message.reply_text(
                "데이터를 인식하지 못했습니다.\n\n"
                "예시:\n"
                "'26년 3월 PL: 매출 124, 영업이익 -3, 순이익 -8\n"
                "'2026년 3월 BS: 자산 450, 부채 320, 자본 130\n"
                "'26년 3월 CF: 영업현금흐름 16, 투자 -85, 기말현금 68"
            )
        return

    # 확인/취소 처리
    if text in ("확인", "저장", "yes", "ㅇ", "ㅇㅇ"):
        pending = ctx.user_data.get("pending_fin")
        if pending:
            await save_financial(update, pending)
            ctx.user_data.pop("pending_fin", None)
            return

    if text in ("취소", "no", "ㄴ"):
        ctx.user_data.pop("pending_fin", None)
        await update.message.reply_text("취소했습니다.")
        return

    # 일반 질문 → Claude
    await update.message.reply_text("분석 중...")
    system = get_hwr_context()
    answer = ask_claude([{"role": "user", "content": text}], system=system, max_tokens=800)
    await update.message.reply_text(answer)

# ── 실행 ──────────────────────────────────────────────────────
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",     start))
    app.add_handler(CommandHandler("status",    status))
    app.add_handler(CommandHandler("atlas",     atlas_cmd))
    app.add_handler(CommandHandler("liquidity", liquidity_cmd))
    app.add_handler(CommandHandler("strategy",  strategy_cmd))
    app.add_handler(CommandHandler("ppa",       ppa_cmd))
    app.add_handler(CommandHandler("ppv",       ppv_cmd))
    app.add_handler(CommandHandler("financial", financial_cmd))
    app.add_handler(MessageHandler(filters.PHOTO, handle_file))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("HWR Bot 시작 (자연어 재무 입력)")
    app.run_polling()
