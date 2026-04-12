import os
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

BOT_TOKEN  = os.environ.get("BOT_TOKEN", "")
CLAUDE_KEY = os.environ.get("CLAUDE_API_KEY", "")
BOT_PW     = os.environ.get("BOT_PASSWORD", "hanwha1234")
FB_URL     = "https://team-dashboard-c0d7b-default-rtdb.asia-southeast1.firebasedatabase.app"

AUTHED = set()

def fb_read(path):
    try:
        res = requests.get(f"{FB_URL}/{path}.json", timeout=5)
        return res.json() or {}
    except:
        return {}

def get_ppv_context():
    data = fb_read("ppv")
    if not data:
        return "[PPV 데이터 없음 — 대시보드 PPV 페이지에서 스냅샷을 찍어주세요]"
    lines = ["[PPV 최신 데이터 — Firebase]"]
    summary = data.get("summary", {})
    if summary:
        lines.append(f"- 총 Risked PPV: ${summary.get('totalRisked','?')}M")
        by_stage = summary.get("byStage", {})
        lines.append(f"- Late: ${by_stage.get('Late',0)}M / Mid: ${by_stage.get('Mid',0)}M / Early: ${by_stage.get('Early',0)}M")
        lines.append(f"- 업데이트: {summary.get('updatedAt','?')}")
    snapshots = data.get("snapshots", {})
    if snapshots:
        snaps = sorted(snapshots.values(), key=lambda x: x.get("ts",0), reverse=True)[:3]
        lines.append("\n[스냅샷 이력]")
        for s in snaps:
            lines.append(f"- {s.get('label','?')}: ${s.get('total','?')}M")
    events = data.get("events", {})
    if events:
        evts = sorted(events.values(), key=lambda x: x.get("ts",""), reverse=True)[:5]
        lines.append("\n[최근 변경]")
        for e in evts:
            proj = f" [{e.get('project')}]" if e.get("project") else ""
            lines.append(f"- {e.get('ts','?')[:16]} {e.get('type','?')}{proj}: {e.get('desc','?')}")
    return "\n".join(lines)

HWR_BASE = """
답변 형식 규칙:
- 마크다운 사용 금지 (**, ##, *, - 등 모두 금지)
- 숫자는 1. 2. 3. 형식 사용
- 줄바꿈으로 구분, 짧고 명확하게
- 이모지는 최소한으로

['26년 매각 대상 - 총 $142M]
- Boulder Solar 3: H확도 $40M NBO (Morrison)
- Bonanza Peak: M확도 $50M NDA/티저 (Lydian)
- Oberon II: M확도 $5M (Disney COD 연장)
- Oberon III: M확도 $10M (Mars 조달 중단)
- Oberon IV: M확도 $5M (TTE NBO 제출)
- Taormina: M확도 $10M (Austin Energy RFP 완료)
- Lavender: M확도 $10M (바이어 리스트 작성)
- Gibson: L확도 $12M (Dominion Shortlist 4월)

[Safe Harbor Class A] Borden, Keystone, Harlem River, Twinkle, Black Star, Florence
[Safe Harbor Class B] Grandview, Stone Fruit, Midfield, Neptune, Appaloosa 2, Martha Fields, Cedar Ridge, Barkley Creek, Greasewood, Intermountain, Prairie Ridge

[Atlas 1st Milestone 달성률 25%]
완료: 2.12(f) / Partially: 2.12(a) 2.12(c) / D-Day 임박: D+10 초과

[운영자산 유동화]
단기매각: TotalJV(Ob1A/Rayos/Ellis/Skysol) + HEUH(Laguna/Astoria)
현금유입 $150~182M, 차입금 제거 $275M, PL -$58~-90M
중장기보유: Ho'Ohana(29년), Oberon 1B, Imeson

[포트폴리오] 94개 프로젝트, PV 13,761 MWac, ESS 10,871 MW
"""

def ask_claude(question):
    if not CLAUDE_KEY:
        return "⚠️ AI 기능 준비 중\n명령어: /status /atlas /ppa /liquidity /strategy /ppv"
    ppv_ctx = get_ppv_context()
    system = HWR_BASE + "\n\n" + ppv_ctx
    try:
        res = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": CLAUDE_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": "claude-haiku-4-5", "max_tokens": 800, "system": system,
                  "messages": [{"role": "user", "content": question}]},
            timeout=30,
        )
        data = res.json()
        if "content" not in data:
            return f"⚠️ {data.get('error',{}).get('message','API 오류')}"
        return data["content"][0]["text"]
    except Exception as e:
        return f"⚠️ 오류: {str(e)}"

def is_authed(uid): return uid in AUTHED

async def show_menu(update):
    await update.message.reply_text(
        "👋 *HWR Dashboard Bot*\n\n"
        "/status — 매각현황\n/atlas — Atlas Milestone\n"
        "/ppa — PPA 진척\n/liquidity — 운영자산 유동화\n"
        "/strategy — 전략 액션\n/ppv — PPV 현황 (Firebase)\n\n"
        "💬 자유 질문도 가능합니다!",
        parse_mode="Markdown"
    )

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if is_authed(update.effective_user.id): await show_menu(update)
    else: await update.message.reply_text("🔐 *HWR Dashboard Bot*\n\n비밀번호를 입력하세요.", parse_mode="Markdown")

async def ppv_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authed(update.effective_user.id):
        await update.message.reply_text("🔐 /start"); return
    await update.message.reply_text("📊 Firebase 조회 중...")
    data = fb_read("ppv")
    summary = data.get("summary", {})
    if not summary:
        await update.message.reply_text("⚠️ PPV 데이터 없음\n대시보드 PPV 페이지에서 📸 스냅샷을 찍어주세요."); return
    by_stage = summary.get("byStage", {})
    msg = (f"📊 *PPV 현황*\n━━━━━━━━━━━━━━\n"
           f"총 Risked PPV: *${summary.get('totalRisked','?')}M*\n\n"
           f"🟢 Late: ${by_stage.get('Late',0):.1f}M\n"
           f"🔵 Mid: ${by_stage.get('Mid',0):.1f}M\n"
           f"🟡 Early: ${by_stage.get('Early',0):.1f}M\n\n"
           f"🕐 {summary.get('updatedAt','?')[:16]}")
    events = data.get("events", {})
    if events:
        evts = sorted(events.values(), key=lambda x: x.get("ts",""), reverse=True)[:3]
        msg += "\n\n*최근 변경:*\n"
        for e in evts:
            proj = f"[{e.get('project')}] " if e.get("project") else ""
            msg += f"• {proj}{e.get('type','?')}: {e.get('desc','?')}\n"
    await update.message.reply_text(msg, parse_mode="Markdown")

async def status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authed(update.effective_user.id):
        await update.message.reply_text("🔐 /start"); return
    await update.message.reply_text(
        "💰 *'26년 매각현황*\n━━━━━━━━━━━━━━\n총 *$142M*\n\n"
        "🟢 H: Boulder Solar 3 $40M — NBO\n"
        "🟡 M: Bonanza Peak $50M / Oberon II~IV $20M / Taormina $10M / Lavender $10M\n"
        "🔴 L: Gibson $12M", parse_mode="Markdown")

async def atlas_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authed(update.effective_user.id):
        await update.message.reply_text("🔐 /start"); return
    await update.message.reply_text(
        "🏔 *Atlas Milestone*\n━━━━━━━━━━━━━━\n달성률: *25%*\n\n"
        "✅ 2.12(f) CAP License\n🟡 2.12(a) 2.12(c) Partially\n🚨 D+10 초과", parse_mode="Markdown")

async def liquidity_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authed(update.effective_user.id):
        await update.message.reply_text("🔐 /start"); return
    await update.message.reply_text(
        "💧 *운영자산 유동화*\n━━━━━━━━━━━━━━\n"
        "단기매각 6개: Ob1A Rayos Ellis Skysol Laguna Astoria\n\n"
        "현금유입 *$150~182M* / 차입금 제거 *$275M* / PL *-$58~-90M*\n\n"
        "중장기보유: Ho'Ohana Ob1B Imeson", parse_mode="Markdown")

async def strategy_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authed(update.effective_user.id):
        await update.message.reply_text("🔐 /start"); return
    await update.message.reply_text(
        "🎯 *전략 액션*\n━━━━━━━━━━━━━━\n✅ EPC Framework\n"
        "🔵 매각 프로세스 / Value-up / Legacy / BESS / ISO GR\n\n이행률: *14%*", parse_mode="Markdown")

async def ppa_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authed(update.effective_user.id):
        await update.message.reply_text("🔐 /start"); return
    await update.message.reply_text(
        "⚡ *PPA 현황*\n━━━━━━━━━━━━━━\n총 18개\n\n"
        "🟡 BL: Atlas 15\n🔵 RFP: Harlem River Taormina Lavender Gibson\n⬜ 미착수: 13개", parse_mode="Markdown")

async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid, text = update.effective_user.id, update.message.text.strip()
    if not is_authed(uid):
        if text == BOT_PW:
            AUTHED.add(uid)
            await update.message.reply_text("✅ 인증되었습니다!")
            await show_menu(update)
        else:
            await update.message.reply_text("❌ 비밀번호 오류. /start")
        return
    await update.message.reply_text("🤔 분석 중...")
    await update.message.reply_text(ask_claude(text))

if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",     start))
    app.add_handler(CommandHandler("status",    status))
    app.add_handler(CommandHandler("atlas",     atlas_cmd))
    app.add_handler(CommandHandler("liquidity", liquidity_cmd))
    app.add_handler(CommandHandler("strategy",  strategy_cmd))
    app.add_handler(CommandHandler("ppa",       ppa_cmd))
    app.add_handler(CommandHandler("ppv",       ppv_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("🤖 HWR Bot 시작! (Firebase 연동)")
    app.run_polling()
