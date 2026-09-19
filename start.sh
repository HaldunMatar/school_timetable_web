#!/usr/bin/env bash
# start.sh — تشغيل نسخة الويب محلياً على macOS/Linux.
#
# ما يفعله:
#   1) ينشئ venv إن لم يكن موجوداً
#   2) يثبّت/يحدّث المتطلبات (فقط إن تغيّر requirements.txt)
#   3) يوقف أي خادم قديم على نفس المنفذ
#   4) يبدأ الخادم في الخلفية
#   5) ينتظر جاهزية /healthz
#   6) يفتح المتصفح تلقائياً (macOS)
#   7) يبقى في المقدمة — Ctrl+C يوقف كل شيء نظيفاً
#
# الاستخدام:
#   ./start.sh          # المنفذ الافتراضي 8000
#   PORT=8080 ./start.sh # منفذ آخر

set -e
cd "$(dirname "$0")"

# ---------- ألوان ----------
G='\033[0;32m'; Y='\033[1;33m'; B='\033[0;36m'; R='\033[0;31m'; N='\033[0m'; BOLD='\033[1m'

PORT="${PORT:-8000}"
URL="http://127.0.0.1:$PORT"
MARKER=".venv/.deps-installed"

echo -e "${BOLD}${B}▶ برنامج توزيع الأساتذة والحصص — نسخة الويب${N}"
echo ""

# ---------- 1. venv ----------
if [ ! -d .venv ]; then
  echo -e "${Y}▸ إنشاء البيئة الافتراضية (.venv)...${N}"
  python3 -m venv .venv
fi
source .venv/bin/activate

# ---------- 2. deps ----------
if [ ! -f "$MARKER" ] || [ requirements.txt -nt "$MARKER" ]; then
  echo -e "${Y}▸ تثبيت / تحديث المتطلبات...${N}"
  pip install --quiet --upgrade pip
  pip install --quiet -r requirements.txt
  touch "$MARKER"
fi

# ---------- 3. أوقف أي خادم قديم على نفس المنفذ ----------
if lsof -ti:$PORT >/dev/null 2>&1; then
  OLD_PIDS=$(lsof -ti:$PORT | tr '\n' ' ')
  echo -e "${Y}▸ إيقاف خادم قائم على المنفذ $PORT (PIDs=$OLD_PIDS)...${N}"
  lsof -ti:$PORT | xargs kill 2>/dev/null || true
  sleep 1
fi

# ---------- 4. بدء الخادم ----------
mkdir -p .venv
LOG=".venv/server.log"
echo -e "${Y}▸ بدء الخادم على المنفذ $PORT...${N}"
python -m timetable_web > "$LOG" 2>&1 &
SERVER_PID=$!

# تنظيف عند الخروج (Ctrl+C أو خطأ)
cleanup() {
  echo ""
  echo -e "${Y}▸ إيقاف الخادم (PID=$SERVER_PID)...${N}"
  kill "$SERVER_PID" 2>/dev/null || true
  wait "$SERVER_PID" 2>/dev/null || true
  echo -e "${G}✓ تم الإيقاف.${N}"
}
trap cleanup EXIT INT TERM

# ---------- 5. انتظار جاهزية /healthz ----------
echo -n "  انتظار جاهزية الخادم"
READY=0
for _ in $(seq 1 40); do
  if curl -sf "$URL/healthz" >/dev/null 2>&1; then
    READY=1
    break
  fi
  echo -n "."
  sleep 0.25
done
echo ""

if [ "$READY" -ne 1 ]; then
  echo -e "${R}✗ الخادم لم يستجب خلال 10 ثوانٍ. آخر سطور السجل:${N}"
  tail -25 "$LOG"
  exit 1
fi

# ---------- 6. الحالة والروابط ----------
echo ""
echo -e "${G}${BOLD}✓ الخادم يعمل!${N}"
echo ""
echo -e "  ${BOLD}الرابط الرئيسي:${N}   ${B}$URL${N}"
echo ""
echo -e "  التبويبات:"
echo -e "    • $URL/                  الرئيسية"
echo -e "    • $URL/dashboard          لوحة المعلومات"
echo -e "    • $URL/teachers           قائمة الأساتذة"
echo -e "    • $URL/subjects           البيانات"
echo -e "    • $URL/constraints        قيود الجدولة"
echo -e "    • $URL/solve              التوليد"
echo -e "    • $URL/log                سجل العمليات"
echo ""
echo -e "  ${BOLD}سجل الخادم:${N}      tail -f $LOG"
echo -e "  ${BOLD}الإيقاف:${N}          Ctrl+C (هنا) أو kill $SERVER_PID"
echo ""

# ---------- 7. افتح المتصفح تلقائياً (macOS) ----------
if [[ "$OSTYPE" == "darwin"* ]] && command -v open >/dev/null; then
  open "$URL"
elif [[ "$OSTYPE" == "linux"* ]] && command -v xdg-open >/dev/null; then
  xdg-open "$URL" >/dev/null 2>&1 &
fi

echo -e "${Y}اضغط Ctrl+C لإيقاف الخادم.${N}"
wait "$SERVER_PID"
