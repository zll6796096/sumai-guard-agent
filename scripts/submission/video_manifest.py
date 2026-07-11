from pathlib import Path


BASE = Path.home() / "Movies" / "SumaiGuard-Hackathon-2026"
SOURCE_COPY = BASE / "source" / "screen-recording.mp4"
WORK = BASE / "work"
FINAL_PATH = BASE / "sumai-guard-hackathon-demo-2026.mp4"

SEGMENTS = [
    {
        "id": "01_problem",
        "type": "card",
        "duration": 7,
        "heading": "転倒する前に、親の家を一枚で点検",
        "body": "離れて暮らす家族が、事故の前に安全対話を始めるためのAIエージェント",
        "caption_ja": "離れて暮らす親の家。見過ごされる危険。",
        "narration_ja": "離れて暮らす親の家。転倒につながる危険は、事故が起きるまで見過ごされがちです。",
    },
    {
        "id": "02_agent",
        "type": "card",
        "duration": 8,
        "heading": "一枚の写真から、次の行動まで",
        "body": "見える危険を抽出 → 決定論ルールで判断 → 3段階の行動へ",
        "caption_ja": "AI Agent：確認・判断・タスク整理",
        "narration_ja": "このAIエージェントは、一枚の写真から見える危険を確認し、次の行動まで整理します。",
    },
    {
        "id": "03_input",
        "type": "demo",
        "duration": 9,
        "source_start": 0,
        "source_duration": 4,
        "heading": "質問票なし。写真を一枚。",
        "body": "部屋を選び、カメラまたはライブラリから入力",
        "caption_ja": "1 PHOTO IN",
        "narration_ja": "質問票は不要です。部屋を選び、写真を一枚撮影、または選択します。",
    },
    {
        "id": "04_analysis",
        "type": "demo",
        "duration": 6,
        "source_start": 4,
        "source_duration": 24,
        "heading": "Cloud Run × Gemini 2.5 Flash",
        "body": "転倒・滑り・つまずきの候補を抽出",
        "caption_ja": "REAL GEMINI / STRICT MODE",
        "narration_ja": "Cloud Run上で、Gemini 2.5 Flashが、転倒、滑り、つまずきの候補を抽出します。",
    },
    {
        "id": "05_visible_risk",
        "type": "demo",
        "duration": 14,
        "source_start": 28,
        "source_duration": 10,
        "heading": "見える危険を、見える形に",
        "body": "赤い枠と慎重な根拠説明",
        "caption_ja": "VISIBLE EVIDENCE ONLY",
        "narration_ja": "危険箇所を赤い枠で可視化。写真で確認できる根拠だけを、慎重に提示します。",
    },
    {
        "id": "06_actions",
        "type": "demo",
        "duration": 17,
        "source_start": 38,
        "source_duration": 17,
        "heading": "迷わない、3段階の次の行動",
        "body": "今日できること / 福祉用具の相談 / 専門施工",
        "caption_ja": "GEMINIは候補抽出。行動区分は決定論ルール。",
        "narration_ja": "その後、決定論ルールで、家族が今日できること、福祉用具の相談、専門施工の三段階に分けます。",
    },
    {
        "id": "07_boundary",
        "type": "card",
        "duration": 8,
        "heading": "安全のための境界",
        "body": "画像保存なし / EXIF除去 / 専門家への相談を促す",
        "caption_ja": "医療・介護・保険・施工判断を置き換えません",
        "narration_ja": "画像は保存せず、位置情報を除去。医療、介護、保険、施工判断の代わりにはなりません。",
    },
    {
        "id": "08_evidence",
        "type": "card",
        "duration": 7,
        "heading": "つくる。まわす。とどける。",
        "body": "Public GitHub / Cloud Run / Gemini strict mode / 34 tests passed",
        "caption_ja": "事故の前に、家族の安全対話を。",
        "narration_ja": "公開コードと動作デモはこちら。事故の前に、家族の安全対話を始めます。",
    },
]
