"""
Analyze scraped Vocus articles using A+B+C strategy criteria.
Only extract high-value content per analyst rules.
"""
import os
import re
from pathlib import Path
import anthropic

VOCUS_DIR = Path("docs/vocus")
OUTPUT_FILE = Path("docs/strategy_complete.md")
STRATEGY_DIR = Path("strategy")

ANALYST_PROMPT = """你是 A+B+C 策略的資深分析師。

【判斷標準】
讀取任何文章時，只保留以下類型的內容：

有價值的內容 ✅
- 具體的進出場條件（有數字或明確描述）
- 籌碼判讀的具體方法
- 年線判斷的量化標準
- 案例分析（有股票代號+時間點）
- B2訊號的具體識別方式

忽略的內容 ❌
- 心靈雞湯、勵志語句
- 廣告、贊助、訂閱資訊
- 社交互動文字（喜歡、留言）
- 沒有具體條件的模糊描述
- 重複出現的相同概念

【輸出格式】
每篇文章處理完後只輸出：
- 核心規則：[具體條件]
- 案例：[股票代號 + 時間點 + 對應條件]（若有）
- 程式可實作：[是/否] + 實作建議

以下是文章內容：

{content}
"""

SYNTHESIS_PROMPT = """你是 A+B+C 策略的資深分析師。

以下是從多篇文章萃取出的策略重點。請整合所有資訊，輸出完整的策略文件。

【文章萃取結果】
{extracted}

【輸出結構】
# A+B+C 完整策略文件

## A條件：年線判斷
- 量化標準（MA240 斜率、位置、距離）
- 判斷規則（具體數字）
- 例外情況

## B條件：籌碼判讀
### B1 - 外資
- 判斷規則（持股比例、買超天數、金額）

### B2 - 投信
- B2訊號識別方式（具體條件）
- 連續買超天數標準

### B3 - 融資
- 融資餘額判斷規則

## C條件：進場時機
- 具體進場條件（K線型態、量能）
- 時間過濾條件

## 出場條件
- 停損規則（%數或條件）
- 停利規則
- 強制出場條件

## 評分權重建議
| 條件 | 權重 | 說明 |
|------|------|------|
| A    |      |      |
| B1   |      |      |
| B2   |      |      |
| B3   |      |      |
| C    |      |      |

## 案例庫
| 股票 | 時間點 | 符合條件 | 結果 |
|------|--------|----------|------|
"""


def analyze_article(client: anthropic.Anthropic, title: str, content: str) -> str:
    # Truncate to avoid token limits
    content_truncated = content[:8000] if len(content) > 8000 else content
    prompt = ANALYST_PROMPT.format(content=f"標題：{title}\n\n{content_truncated}")

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def synthesize_strategy(client: anthropic.Anthropic, extractions: list[str]) -> str:
    combined = "\n\n---\n\n".join(extractions)
    # Truncate if too long
    if len(combined) > 30000:
        combined = combined[:30000] + "\n...(截斷)"

    prompt = SYNTHESIS_PROMPT.format(extracted=combined)

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def get_strategy_files() -> dict[str, str]:
    files = {}
    for f in STRATEGY_DIR.glob("*.py"):
        try:
            files[f.name] = f.read_text(encoding="utf-8")
        except Exception:
            pass
    return files


def compare_with_code(client: anthropic.Anthropic, strategy_doc: str, code_files: dict) -> str:
    code_summary = "\n\n".join(
        f"### {name}\n```python\n{content[:3000]}\n```"
        for name, content in code_files.items()
    )

    prompt = f"""你是 A+B+C 策略的資深分析師。

以下是完整策略文件，以及目前程式碼中的 strategy/ 模組。

請輸出對照表，格式如下：

# 策略實作對照表

## ✅ 已實作
| 條件 | 程式位置 | 說明 |

## ❌ 未實作
| 條件 | 建議實作方式 |

## ⚠️ 實作有誤
| 條件 | 問題描述 | 修正建議 |

【策略文件】
{strategy_doc[:5000]}

【程式碼】
{code_summary}
"""

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=3000,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERROR: ANTHROPIC_API_KEY not set")
        return

    client = anthropic.Anthropic(api_key=api_key)

    # Phase 3: Analyze each article
    article_files = list(VOCUS_DIR.glob("*.md"))
    if not article_files:
        print("No articles found in docs/vocus/")
        return

    print(f"Found {len(article_files)} articles to analyze")
    extractions = []

    for i, filepath in enumerate(article_files, 1):
        title = filepath.stem.replace("_", " ")
        content = filepath.read_text(encoding="utf-8")
        print(f"\n[{i}/{len(article_files)}] Analyzing: {title[:60]}")

        extraction = analyze_article(client, title, content)
        extractions.append(f"## 文章：{title}\n\n{extraction}")
        print(extraction[:200] + "...")

    # Synthesize complete strategy doc
    print("\n\nSynthesizing complete strategy document...")
    strategy_doc = synthesize_strategy(client, extractions)

    # Phase 4: Compare with code
    print("\nComparing with strategy/ code...")
    code_files = get_strategy_files()
    comparison = compare_with_code(client, strategy_doc, code_files)

    # Write output
    output = f"{strategy_doc}\n\n---\n\n{comparison}"
    OUTPUT_FILE.write_text(output, encoding="utf-8")

    print(f"\n{'='*50}")
    print(f"完成！輸出至 {OUTPUT_FILE}")
    print(f"{'='*50}")
    print("\n" + strategy_doc[:500])


if __name__ == "__main__":
    main()
