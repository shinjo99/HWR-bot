import os
import json
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

# ── 설정 ──────────────────────────────────────────
BOT_TOKEN     = os.environ.get("BOT_TOKEN", "")
CLAUDE_KEY    = os.environ.get("CLAUDE_API_KEY", "")
ALLOWED_IDS   = set(int(x) for x in os.environ.get("ALLOWED_IDS", "").split(",") if x.strip())

# ── HWR 데이터 (Dashboard와 동기화) ──────────────
HWR_CONTEXT = """
당신은 HWR(Hanwha Q CELLS USA / HEUH) 미국 개발 사업 대시보드의 AI 어시스트입니다.
다음 데이터를 기반으로 질문에 답하세요.

[포트폴리오]
- 총 94개 프로젝트 (HWR + Q-cells)
- PV: 13,761 MWac / ESS: 10,871 MW

['26년 매각 대상 - 총 $142M]
- Boulder Solar 3: H확도, $40M, NBO 단계 (Morrison 협의 중)
- Bonanza Peak: M확도, $50M, NDA/티저 (Lydian 초기 협의)
- Oberon II: M확도, $5M, NDA/티저 (Disney COD 연장 논의)
- Oberon III: M확도, $10M, NDA/티저 (Mars 조달 중단)
- Oberon IV: M확도, $5M, NDA/티저 (TTE NBO 제출)
- Taormina: M확도, $10M, NDA/티저 (Austin Energy RFP 완료)
- Lavender: M확도, $10M, NDA/티저 (바이어 리스트 작성)
- Gibson: L확도, $12M, 준비 (Dominion Shortlist 4월)

[Safe Harbor - Class A]
Borden, Keystone, Harlem River, Twinkle, Black Star, Florence

[Safe Harbor - Class B]
Grandview, Stone Fruit, Midfield, Neptune, Appaloosa 2, Martha Fields,
Cedar Ridge, Barkley Creek, Greasewood, Intermountain, Prairie Ridge

[Atlas 1st Milestone - 달성률 25%]
2.12(a)~(q) 12개 항목 중 일부 Partially/완료

[운영자산 유동화]
- 단기매각: TotalJV(Ob1A/Rayos/Ellis/Skysol) + HEUH(Laguna/Astoria)
  예상 현금유입 $150~182M, 차입금 제거 $275M, PL 영향 -$58~-90M
- 중장기보유: Ho'Ohana(ITC recapture 29년까지), Oberon 1B, Imeson

[전략 액션 아이템]
1. 선제적 매각 프로세스 구체화 (진행중)
2. EPC Framework 확정 (완료)
3. Value-up 방안 구체화 (진행중)
4. Legacy 자산 전략 과제 (진행중)
5. BESS 중심 성장 전략 수립 (진행중)
6. ISO별 Local GR 방안 (진행중)
"""

# ── 보안: 허용된 사용자만 ──────────────────────
def is_allowed(user_id: int) -> bool:
    if not ALLOWED_IDS:  # 설정 안 되어있으면 일단 허용 (초기 테스트용)
        return True
    return user_id in ALLOWED_IDS

# ── Claude API 호출 ────────────────────────────
def ask_claude(question: str) -> str:
    if not CLAUDE_KEY:
        return "⚠️ Claude API 키가 설정되지 않았습니다."
    try:
        res = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": CLAUDE_KEY,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-6",
                "max_tokens": 1000,
                "system": HWR_CONTEXT,
                "messages": [{"role": "user", "content": question}],
            },
            timeout=30,
        )
        data = res.json()
        return data["content"][0]["text"]
    except Exception as e:
        return f"⚠️ 오류: {str(e)}"

# ── 명령어 핸들러 ──────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid = update.effective_user.id
    if not is_allowed(uid):
        await update.message.reply_text("⛔ 접근 권한이 없습니다.")
        return
    await update.message.reply_text(
        "👋 HWR Dashboard Bot입니다.\n\n"
        "📋 *사용 가능한 명령어:*\n"
        "/status - 매각현황 요약\n"
        "/atlas - Atlas Milestone 현황\n"
        "/ppa - PPA 진척 현황\n"
        "/liquidity - 운영자산 유동화\n"
        "/strategy - 전략 액션 아이템\n\n"
        "💬 또는 자유롭게 질문하세요!\n"
        "예: _Bonanza Peak 현황은?_",
        parse_mode="Markdown"
    )

async def status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("⛔ 접근 권한이 없습니다.")
        return
    msg = (
        "💰 *'26년 매각현황 요약*\n"
        "━━━━━━━━━━━━━━\n"
        "총 예상 매각이익: *$142M*\n\n"
        "🟢 H확도: Boulder Solar 3 ($40M) — NBO\n"
        "🟡 M확도:\n"
        "  • Bonanza Peak $50M — NDA/티저\n"
        "  • Oberon II $5M — NDA/티저\n"
        "  • Oberon III $10M — NDA/티저\n"
        "  • Oberon IV $5M — NDA/티저\n"
        "  • Taormina $10M — NDA/티저\n"
        "  • Lavender $10M — NDA/티저\n"
        "🔴 L확도: Gibson $12M — 준비"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def atlas_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return
    msg = (
        "🏔 *Atlas North 1st Milestone*\n"
        "━━━━━━━━━━━━━━\n"
        "전체 달성률: *25%* (12개 항목)\n\n"
        "✅ 완료: 2.12(f) CAP License\n"
        "🟡 Partially: 2.12(a) Tax/Insurance, 2.12(c) PPA Amendment\n"
        "⏳ 미착수: 나머지 항목\n\n"
        "🚨 D-Day 임박: 2.12(a),(f) — D+10 초과"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def liquidity_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return
    msg = (
        "💧 *운영자산 유동화*\n"
        "━━━━━━━━━━━━━━\n"
        "*단기 매각 (6개):*\n"
        "TotalJV: Ob1A, Rayos, Ellis, Skysol\n"
        "HEUH: Laguna (협의중), Astoria (준비중)\n\n"
        "예상 현금유입: *$150~182M*\n"
        "차입금 제거: *$275M*\n"
        "PL 영향: *-$58~-90M*\n\n"
        "*중장기 보유 (3개):*\n"
        "Ho'Ohana (29년까지), Oberon 1B, Imeson"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def strategy_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return
    msg = (
        "🎯 *전략 액션 아이템*\n"
        "━━━━━━━━━━━━━━\n"
        "✅ EPC Framework 확정 (완료)\n"
        "🔵 선제적 매각 프로세스 구체화 (진행중)\n"
        "🔵 Value-up 방안 구체화 (진행중)\n"
        "🔵 Legacy 자산 전략 과제 (진행중)\n"
        "🔵 BESS 중심 성장 전략 수립 (진행중)\n"
        "🔵 ISO별 Local GR 방안 (진행중)\n\n"
        "전체 이행률: *14%* (1/7)"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def ppa_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return
    msg = (
        "⚡ *PPA 진척 현황*\n"
        "━━━━━━━━━━━━━━\n"
        "총 18개 프로젝트\n\n"
        "🟡 BL: Atlas 15 (논의 진행)\n"
        "🔵 RFP: Harlem River, Taormina, Lavender, Gibson\n"
        "⬜ 미착수: 나머지 13개\n\n"
        "계약 완료: 0건"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("⛔ 접근 권한이 없습니다.")
        return
    question = update.message.text
    await update.message.reply_text("🤔 분석 중...")
    answer = ask_claude(question)
    await update.message.reply_text(answer)

# ── 실행 ──────────────────────────────────────
if __name__ == "__main__":
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",      start))
    app.add_handler(CommandHandler("status",     status))
    app.add_handler(CommandHandler("atlas",      atlas_cmd))
    app.add_handler(CommandHandler("liquidity",  liquidity_cmd))
    app.add_handler(CommandHandler("strategy",   strategy_cmd))
    app.add_handler(CommandHandler("ppa",        ppa_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("🤖 HWR Bot 시작!")
    app.run_polling()
