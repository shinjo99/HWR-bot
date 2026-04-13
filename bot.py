import os
import io
import json
import requests
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

BOT_TOKEN  = os.environ.get("BOT_TOKEN", "")
CLAUDE_KEY = os.environ.get("CLAUDE_API_KEY", "")
BOT_PW     = os.environ.get("BOT_PASSWORD", "hanwha1234")
FB_URL     = "https://team-dashboard-c0d7b-default-rtdb.asia-southeast1.firebasedatabase.app"

AUTHED = set()

# ── Firebase 읽기/쓰기 ────────────────────────────
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

def fb_put(path, data):
    try:
        res = requests.put(f"{FB_URL}/{path}.json", json=data, timeout=5)
        return res.status_code == 200
    except:
        return False

# ── PPV 컨텍스트 ──────────────────────────────────
def get_ppv_context():
    data = fb_read("ppv")
    if not data:
        return "[PPV 데이터 없음]"
    lines = ["[PPV 최신 데이터]"]
    summary = data.get("summary", {})
    if summary:
        lines.append(f"총 Risked PPV: ${summary.get('totalRisked','?')}M")
        by_stage = summary.get("byStage", {})
        lines.append(f"Late: ${by_stage.get('Late',0)}M / Mid: ${by_stage.get('Mid',0)}M / Early: ${by_stage.get('Early',0)}M")
    return "\n".join(lines)

def get_financial_context():
    data = fb_read("financial")
    if not data:
        return "[재무 데이터 없음]"
    lines = ["[재무 데이터 — Firebase]"]
    for stmt in ["pl", "bs", "cf"]:
        stmt_data = data.get(stmt, {})
        if stmt_data:
            years = sorted(stmt_data.keys(), reverse=True)[:1]
            for year in years:
                months = sorted(stmt_data[year].keys(), reverse=True)[:3]
                lines.append(f"\n[{stmt.upper()} {year}년]")
                for month in months:
                    m_data = stmt_data[year][month]
                    items = ", ".join([f"{k}={v}" for k, v in m_data.items() if k != "updated_at"])
                    lines.append(f"  {month}월: {items}")
    return "\n".join(lines)

# ── HWR 컨텍스트 ──────────────────────────────────
HWR_BASE = """
답변 형식 규칙:
- 마크다운 사용 금지 (**, ##, *, - 등 모두 금지)
- 숫자는 1. 2. 3. 형식 사용
- 줄바꿈으로 구분, 짧고 명확하게
- 이모지 사용 금지
- 사람이 보고하듯 자연스럽게

당신은 HWR(Hanwha Q CELLS USA / HEUH) 미국 개발 사업 담당자입니다.
아래 데이터를 바탕으로 질문에 답하세요.

['26년 매각 대상 - 총 $142M]
Boulder Solar 3: H확도 $40M NBO (Morrison)
Bonanza Peak: M확도 $50M NDA/티저 (Lydian)
Oberon II: M확도 $5M (Disney COD 연장)
Oberon III: M확도 $10M (Mars 조달 중단)
Oberon IV: M확도 $5M (TTE NBO 제출)
Taormina: M확도 $10M (Austin Energy RFP 완료)
Lavender: M확도 $10M (바이어 리스트 작성)
Gibson: L확도 $12M (Dominion Shortlist 4월)

[Safe Harbor Class A] Borden, Keystone, Harlem River, Twinkle, Black Star, Florence
[Safe Harbor Class B] Grandview, Stone Fruit, Midfield, Neptune, Appaloosa 2, Martha Fields,
Cedar Ridge, Barkley Creek, Greasewood, Intermountain, Prairie Ridge

[Atlas 1st Milestone 달성률 25%]
완료: 2.12(f) / Partially: 2.12(a) 2.12(c) / D-Day 임박: D+10 초과

[운영자산 유동화]
단기매각: TotalJV(Ob1A/Rayos/Ellis/Skysol) + HEUH(Laguna/Astoria)
현금유입 $150~182M, 차입금 제거 $275M, PL -$58~-90M
중장기보유: Ho'Ohana(29년), Oberon 1B, Imeson

[포트폴리오] 94개 프로젝트, PV 13,761 MWac, ESS 10,871 MW
"""

# ── Claude API ────────────────────────────────────
def ask_claude(question, extra_context=""):
    if not CLAUDE_KEY:
        return "AI 기능 준비 중\n명령어: /status /atlas /ppa /liquidity /strategy /ppv /financial"
    system = HWR_BASE + "\n\n" + get_ppv_context() + "\n\n" + get_financial_context()
    if extra_context:
        system += "\n\n" + extra_context
    try:
        res = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": CLAUDE_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": "claude-haiku-4-5", "max_tokens": 1000, "system": system,
                  "messages": [{"role": "user", "content": question}]},
            timeout=30,
        )
        data = res.json()
        if "content" not in data:
            return f"오류: {data.get('error',{}).get('message','API 오류')}"
        return data["content"][0]["text"]
    except Exception as e:
        return f"오류: {str(e)}"

def ask_claude_with_image(question, image_b64, media_type="image/jpeg"):
    """이미지와 함께 Claude에 질문"""
    if not CLAUDE_KEY:
        return "AI 기능 준비 중"
    try:
        res = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={"x-api-key": CLAUDE_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={
                "model": "claude-haiku-4-5",
                "max_tokens": 1500,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": image_b64}},
                        {"type": "text", "text": question}
                    ]
                }]
            },
            timeout=60,
        )
        data = res.json()
        if "content" not in data:
            return f"오류: {data.get('error',{}).get('message','API 오류')}"
        return data["content"][0]["text"]
    except Exception as e:
        return f"오류: {str(e)}"

# ── 파라미터 파싱 ──────────────────────────────────
def parse_params(text):
    """'매출=124 EBITDA=19.5 월=3' 형식 파싱"""
    params = {}
    for part in text.split():
        if "=" in part:
            k, v = part.split("=", 1)
            try:
                params[k.strip()] = float(v.strip())
            except:
                params[k.strip()] = v.strip()
    return params

# ── 인증 ──────────────────────────────────────────
def is_authed(uid): return uid in AUTHED

# ── 메뉴 ──────────────────────────────────────────
async def show_menu(update):
    await update.message.reply_text(
        "HWR Dashboard Bot\n\n"
        "조회 명령어\n"
        "  /status      매각현황\n"
        "  /atlas       Atlas Milestone\n"
        "  /ppa         PPA 진척\n"
        "  /liquidity   운영자산 유동화\n"
        "  /strategy    전략 액션 아이템\n"
        "  /ppv         PPV 현황\n"
        "  /financial   재무 현황\n\n"
        "데이터 업로드\n"
        "  /pl  월=3 매출=124 EBITDA=19.5 순이익=3.4 CAPEX=892\n"
        "  /bs  월=3 자산=1578 부채=1154 자본=424\n"
        "  /cf  월=3 영업=16.2 투자=-348 재무=268 기말=68\n"
        "  파일/이미지 첨부 → 자동 파싱 후 저장\n\n"
        "자유롭게 질문하셔도 됩니다."
    )

# ── 핸들러: 조회 ──────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if is_authed(update.effective_user.id): await show_menu(update)
    else: await update.message.reply_text("HWR Dashboard Bot입니다.\n비밀번호를 입력하세요.")

async def financial_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authed(update.effective_user.id):
        await update.message.reply_text("비밀번호를 먼저 입력하세요. /start"); return
    await update.message.reply_text("조회 중...")
    data = fb_read("financial")
    if not data:
        await update.message.reply_text("재무 데이터가 없습니다.\n/pl /bs /cf 명령어로 업로드해주세요."); return
    msg = "재무 현황\n\n"
    labels = {"pl": "P&L", "bs": "B/S", "cf": "C/F"}
    for stmt, label in labels.items():
        stmt_data = data.get(stmt, {})
        if not stmt_data: continue
        years = sorted(stmt_data.keys(), reverse=True)[:1]
        for year in years:
            months = sorted(stmt_data[year].keys(), key=lambda x: int(x), reverse=True)[:3]
            msg += f"{label} ({year}년)\n"
            for month in months:
                m_data = stmt_data[year][month]
                items = "  ".join([f"{k} {v}" for k, v in m_data.items() if k != "updated_at"])
                msg += f"  {month}월  {items}\n"
            msg += "\n"
    await update.message.reply_text(msg)

async def ppv_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authed(update.effective_user.id):
        await update.message.reply_text("비밀번호를 먼저 입력하세요. /start"); return
    await update.message.reply_text("조회 중...")
    data = fb_read("ppv")
    summary = data.get("summary", {})
    if not summary:
        await update.message.reply_text("PPV 데이터 없음\n대시보드 PPV 페이지에서 스냅샷을 찍어주세요."); return
    by_stage = summary.get("byStage", {})
    updated = summary.get('updatedAt','?')[:10]
    msg = (
        f"PPV 현황 ({updated} 기준)\n\n"
        f"총 Risked PPV  ${summary.get('totalRisked','?')}M\n"
        f"  Late Stage   ${by_stage.get('Late',0):.1f}M\n"
        f"  Mid Stage    ${by_stage.get('Mid',0):.1f}M\n"
        f"  Early Stage  ${by_stage.get('Early',0):.1f}M\n"
    )
    events = data.get("events", {})
    if events:
        evts = sorted(events.values(), key=lambda x: x.get("ts",""), reverse=True)[:3]
        msg += "\n최근 변경\n"
        for e in evts:
            proj = f"{e.get('project')}  " if e.get("project") else ""
            msg += f"  {e.get('ts','?')[:10]}  {proj}{e.get('type','?')}  {e.get('desc','?')}\n"
    await update.message.reply_text(msg)

async def status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authed(update.effective_user.id):
        await update.message.reply_text("비밀번호를 먼저 입력하세요. /start"); return
    await update.message.reply_text(
        "'26년 매각현황\n\n"
        "총 목표  $142M\n\n"
        "H확도\n"
        "  Boulder Solar 3  $40M  NBO 협의 중\n\n"
        "M확도\n"
        "  Bonanza Peak     $50M  NDA/티저\n"
        "  Oberon II        $5M   NDA/티저\n"
        "  Oberon III       $10M  NDA/티저\n"
        "  Oberon IV        $5M   NDA/티저\n"
        "  Taormina         $10M  NDA/티저\n"
        "  Lavender         $10M  NDA/티저\n\n"
        "L확도\n"
        "  Gibson           $12M  준비 중"
    )

async def atlas_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authed(update.effective_user.id):
        await update.message.reply_text("비밀번호를 먼저 입력하세요. /start"); return
    await update.message.reply_text(
        "Atlas North 1st Milestone\n\n"
        "전체 달성률  25%  (12개 항목)\n\n"
        "완료      2.12(f) CAP License\n"
        "진행 중   2.12(a) Tax/Insurance\n"
        "          2.12(c) PPA Amendment\n"
        "미착수    나머지 항목\n\n"
        "D-Day 임박  2.12(a), 2.12(f)  D+10 초과"
    )

async def liquidity_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authed(update.effective_user.id):
        await update.message.reply_text("비밀번호를 먼저 입력하세요. /start"); return
    await update.message.reply_text(
        "운영자산 유동화\n\n"
        "단기 매각 (6개)\n"
        "  TotalJV   Ob1A, Rayos, Ellis, Skysol\n"
        "  HEUH      Laguna, Astoria\n\n"
        "예상 현금유입   $150~182M\n"
        "차입금 제거     $275M\n"
        "PL 영향         -$58~-90M\n\n"
        "중장기 보유 (3개)\n"
        "  Ho'Ohana (ITC recapture 2029년까지)\n"
        "  Oberon 1B\n"
        "  Imeson"
    )

async def strategy_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authed(update.effective_user.id):
        await update.message.reply_text("비밀번호를 먼저 입력하세요. /start"); return
    await update.message.reply_text(
        "전략 액션 아이템\n\n"
        "1. 선제적 매각 프로세스 구체화   진행 중\n"
        "2. EPC Framework 확정           완료\n"
        "3. Value-up 방안 구체화         진행 중\n"
        "4. Legacy 자산 전략 과제        진행 중\n"
        "5. BESS 중심 성장 전략 수립     진행 중\n"
        "6. ISO별 Local GR 방안          진행 중\n\n"
        "전체 이행률  14%  (1/7)"
    )

async def ppa_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_authed(update.effective_user.id):
        await update.message.reply_text("비밀번호를 먼저 입력하세요. /start"); return
    await update.message.reply_text(
        "PPA 진척 현황\n\n"
        "총 18개 프로젝트\n\n"
        "BL 단계   Atlas 15 (논의 진행)\n"
        "RFP 진행  Harlem River, Taormina, Lavender, Gibson\n"
        "미착수    13개\n\n"
        "계약 완료  0건"
    )

# ── 핸들러: 데이터 업로드 ─────────────────────────
async def pl_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """P&L 업로드: /pl 월=3 매출=124 EBITDA=19.5 순이익=3.4 CAPEX=892"""
    if not is_authed(update.effective_user.id):
        await update.message.reply_text("비밀번호를 먼저 입력하세요. /start"); return
    text = update.message.text.replace("/pl", "").strip()
    if not text:
        await update.message.reply_text(
            "사용법:\n/pl 월=3 매출=124 EBITDA=19.5 순이익=3.4 CAPEX=892\n\n"
            "항목: 월, 연도(기본 2026), 매출, EBITDA, 순이익, CAPEX, 매출원가, 영업이익"
        ); return
    params = parse_params(text)
    month = int(params.pop("월", 0))
    year  = int(params.pop("연도", 2026))
    if not month:
        await update.message.reply_text("월을 입력해주세요. 예: 월=3"); return
    params["updated_at"] = __import__("datetime").datetime.now().isoformat()[:16]
    if fb_write(f"financial/pl/{year}/{month}", params):
        items = "\n".join([f"  {k}  {v}" for k, v in params.items() if k != "updated_at"])
        await update.message.reply_text(f"P&L {year}년 {month}월 저장 완료\n\n{items}")
    else:
        await update.message.reply_text("저장 실패. 다시 시도해주세요.")

async def bs_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """B/S 업로드: /bs 월=3 자산=1578 부채=1154 자본=424"""
    if not is_authed(update.effective_user.id):
        await update.message.reply_text("비밀번호를 먼저 입력하세요. /start"); return
    text = update.message.text.replace("/bs", "").strip()
    if not text:
        await update.message.reply_text(
            "사용법:\n/bs 월=3 자산=1578 부채=1154 자본=424 부채비율=72\n\n"
            "항목: 월, 연도(기본 2026), 자산, 부채, 자본, 유동자산, 비유동자산, 부채비율"
        ); return
    params = parse_params(text)
    month = int(params.pop("월", 0))
    year  = int(params.pop("연도", 2026))
    if not month:
        await update.message.reply_text("월을 입력해주세요. 예: 월=3"); return
    params["updated_at"] = __import__("datetime").datetime.now().isoformat()[:16]
    if fb_write(f"financial/bs/{year}/{month}", params):
        items = "\n".join([f"  {k}  {v}" for k, v in params.items() if k != "updated_at"])
        await update.message.reply_text(f"B/S {year}년 {month}월 저장 완료\n\n{items}")
    else:
        await update.message.reply_text("저장 실패. 다시 시도해주세요.")

async def cf_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """C/F 업로드: /cf 월=3 영업=16.2 투자=-348 재무=268 기말=68"""
    if not is_authed(update.effective_user.id):
        await update.message.reply_text("비밀번호를 먼저 입력하세요. /start"); return
    text = update.message.text.replace("/cf", "").strip()
    if not text:
        await update.message.reply_text(
            "사용법:\n/cf 월=3 영업=16.2 투자=-348 재무=268 기말=68\n\n"
            "항목: 월, 연도(기본 2026), 영업, 투자, 재무, 기말"
        ); return
    params = parse_params(text)
    month = int(params.pop("월", 0))
    year  = int(params.pop("연도", 2026))
    if not month:
        await update.message.reply_text("월을 입력해주세요. 예: 월=3"); return
    params["updated_at"] = __import__("datetime").datetime.now().isoformat()[:16]
    if fb_write(f"financial/cf/{year}/{month}", params):
        items = "\n".join([f"  {k}  {v}" for k, v in params.items() if k != "updated_at"])
        await update.message.reply_text(f"C/F {year}년 {month}월 저장 완료\n\n{items}")
    else:
        await update.message.reply_text("저장 실패. 다시 시도해주세요.")

# ── 핸들러: 파일/이미지 업로드 ───────────────────
async def handle_file(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """엑셀/이미지 파일 수신 → Claude 파싱 → Firebase 저장"""
    if not is_authed(update.effective_user.id):
        await update.message.reply_text("비밀번호를 먼저 입력하세요. /start"); return

    await update.message.reply_text("파일 분석 중...")

    # 이미지 처리
    if update.message.photo:
        photo = update.message.photo[-1]
        file = await ctx.bot.get_file(photo.file_id)
        file_bytes = await file.download_as_bytearray()
        import base64
        img_b64 = base64.b64encode(file_bytes).decode()
        prompt = (
            "이 이미지에서 재무 데이터를 추출해주세요.\n"
            "P&L, B/S, C/F 중 어떤 데이터인지 파악하고,\n"
            "다음 형식으로만 답하세요 (다른 설명 없이):\n\n"
            "구분: PL 또는 BS 또는 CF\n"
            "연도: YYYY\n"
            "월: M\n"
            "항목1: 값1\n"
            "항목2: 값2\n"
            "..."
        )
        result = ask_claude_with_image(prompt, img_b64, "image/jpeg")
        await process_parsed_data(update, result)
        return

    # 문서 파일 처리 (PDF, Excel 등)
    if update.message.document:
        doc = update.message.document
        file = await ctx.bot.get_file(doc.file_id)
        file_bytes = await file.download_as_bytearray()

        # Excel 파일
        if doc.mime_type in ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                              "application/vnd.ms-excel"] or doc.file_name.endswith(('.xlsx', '.xls')):
            try:
                import openpyxl
                wb = openpyxl.load_workbook(io.BytesIO(file_bytes), data_only=True)
                # 첫 시트 데이터 추출
                ws = wb.active
                rows = []
                for row in ws.iter_rows(min_row=1, max_row=50, values_only=True):
                    if any(cell is not None for cell in row):
                        rows.append([str(c) if c is not None else "" for c in row])
                table_text = "\n".join(["\t".join(r) for r in rows[:30]])

                prompt = (
                    f"다음 엑셀 데이터에서 재무 수치를 추출해주세요.\n\n"
                    f"{table_text}\n\n"
                    "P&L, B/S, C/F 중 어떤 데이터인지 파악하고,\n"
                    "다음 형식으로만 답하세요:\n\n"
                    "구분: PL 또는 BS 또는 CF\n"
                    "연도: YYYY\n"
                    "월: M\n"
                    "항목1: 값1\n"
                    "항목2: 값2"
                )
                result = ask_claude(prompt)
                await process_parsed_data(update, result)
            except ImportError:
                await update.message.reply_text(
                    "Excel 파싱을 위해 openpyxl이 필요합니다.\n"
                    "텍스트 명령어를 사용해주세요:\n"
                    "/pl /bs /cf"
                )
            except Exception as e:
                await update.message.reply_text(f"파일 처리 오류: {str(e)}")
        else:
            await update.message.reply_text(
                "지원하는 파일 형식: 이미지, Excel (.xlsx)\n\n"
                "또는 텍스트 명령어를 사용해주세요:\n"
                "/pl /bs /cf"
            )

async def process_parsed_data(update, result):
    """Claude 파싱 결과를 Firebase에 저장"""
    lines = result.strip().split("\n")
    data = {}
    stmt_type = None
    year = 2026
    month = None

    for line in lines:
        if ":" in line:
            k, v = line.split(":", 1)
            k, v = k.strip(), v.strip()
            if k == "구분":
                stmt_type = v.upper()
            elif k == "연도":
                try: year = int(v)
                except: pass
            elif k == "월":
                try: month = int(v)
                except: pass
            else:
                try:
                    # 숫자에서 단위 제거 (M, 억 등)
                    clean = v.replace("M", "").replace("억", "").replace(",", "").strip()
                    data[k] = float(clean)
                except:
                    data[k] = v

    if not stmt_type or not month or not data:
        await update.message.reply_text(
            "데이터 파싱에 실패했습니다.\n\n"
            "텍스트 명령어로 직접 입력해주세요:\n"
            "/pl 월=3 매출=124 EBITDA=19.5 순이익=3.4"
        )
        return

    import datetime
    data["updated_at"] = datetime.datetime.now().isoformat()[:16]
    path_map = {"PL": "pl", "BS": "bs", "CF": "cf"}
    path_key = path_map.get(stmt_type, stmt_type.lower())

    if fb_write(f"financial/{path_key}/{year}/{month}", data):
        items = "\n".join([f"  {k}  {v}" for k, v in data.items() if k != "updated_at"])
        await update.message.reply_text(
            f"{stmt_type} {year}년 {month}월 저장 완료\n\n{items}\n\n"
            "대시보드 재무 탭에서 확인하세요."
        )
    else:
        await update.message.reply_text("저장 실패. 다시 시도해주세요.")

# ── 핸들러: 텍스트 메시지 ─────────────────────────
async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid, text = update.effective_user.id, update.message.text.strip()
    if not is_authed(uid):
        if text == BOT_PW:
            AUTHED.add(uid)
            await update.message.reply_text("인증되었습니다.")
            await show_menu(update)
        else:
            await update.message.reply_text("비밀번호가 틀렸습니다. /start")
        return
    await update.message.reply_text("분석 중...")
    await update.message.reply_text(ask_claude(text))

# ── 실행 ──────────────────────────────────────────
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
    app.add_handler(CommandHandler("pl",        pl_cmd))
    app.add_handler(CommandHandler("bs",        bs_cmd))
    app.add_handler(CommandHandler("cf",        cf_cmd))
    app.add_handler(MessageHandler(filters.PHOTO, handle_file))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_file))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("HWR Bot 시작 (Firebase + 파일 업로드)")
    app.run_polling()
