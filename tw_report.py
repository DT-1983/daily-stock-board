"""把 daily_stock_analysis 的簡體報告 → 繁體台灣用語 + 修表格 + 存進 obis AI Report/Investment

用法:python tw_report.py <input.md> [-o output.md]
不指定 -o 時自動存到 obis 04_AI Report/Investment/YYYY-MM-DD_美股晨會看板.md
"""
import sys
import os
import re
import argparse
from datetime import datetime
from opencc import OpenCC

OBIS_INVEST = r"C:\Users\Mophy\Documents\Google drive\BB-8 工作區\04_AI Report\Investment"

cc = OpenCC("s2twp")  # 簡→繁 + 台灣慣用詞

# OpenCC 漏掉的金融術語(大陸 → 台灣),在 OpenCC 之後套用
FINANCE_TERMS = {
    "倉位": "部位", "加倉": "加碼", "減倉": "減碼", "建倉": "建立部位",
    "空倉": "空手", "滿倉": "滿持", "重倉": "重壓", "輕倉": "輕持",
    "抄底": "逢低承接", "覆盤": "盤後檢討", "復盤": "盤後檢討",
    "質量": "品質", "成交額": "成交值", "換手率": "週轉率",
    "高位": "高檔", "低位": "低檔", "回調": "回檔", "板塊": "類股",
    "盈利": "獲利", "淨利潤": "淨利", "信號": "訊號", "標的": "標的",
    "走勢": "走勢", "止盈": "停利", "止損": "停損", "個股": "個股",
    "整數關口": "整數關卡", "心理關口": "心理關卡", "接飛刀": "接刀",
    "縮量": "量縮", "放量": "量增", "逆勢": "逆勢", "右側": "右側",
    "回撥": "回檔", "儀表盤": "儀表板", "買入": "買進", "做多": "做多",
    "高低切換": "資金輪動", "權重": "權值", "破位": "破線",
}


def normalize_tables(md: str) -> str:
    """確保每個表格前有空行(Obsidian 表格緊貼文字會跑掉)。"""
    lines = md.split("\n")
    out = []
    for i, line in enumerate(lines):
        is_table = line.lstrip().startswith("|")
        prev = out[-1] if out else ""
        prev_is_table = prev.lstrip().startswith("|")
        # 表格首行前一行不是表格也不是空行 → 插空行
        if is_table and not prev_is_table and prev.strip() != "":
            out.append("")
        out.append(line)
    return "\n".join(out)


def convert(md: str) -> str:
    md = cc.convert(md)
    for a, b in FINANCE_TERMS.items():
        md = md.replace(a, b)
    md = normalize_tables(md)
    return md


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("-o", "--output", default=None)
    args = ap.parse_args()

    with open(args.input, encoding="utf-8") as f:
        md = f.read()
    md_tw = convert(md)

    if args.output:
        out = args.output
    else:
        os.makedirs(OBIS_INVEST, exist_ok=True)
        date = datetime.now().strftime("%Y-%m-%d")
        out = os.path.join(OBIS_INVEST, f"{date}_美股晨會看板.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(md_tw)
    print(f"✅ 繁中報告已存：{out}")


if __name__ == "__main__":
    main()
