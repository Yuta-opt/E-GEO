# GPT-5 + Gemini + Claude 3モデル統合 最終結果

このフォルダをYANS 2026向けTOEIC E-GEO実験の**正式な最終結果**とします。

## 評価モデル

- GPT-5
- Gemini 3.5 Flash
- Claude Sonnet 4.5

## 状態

このREADMEは公開先を先に固定するために作成しています。数値・CSV・Excel・PNGは、ローカルでClaude回収済みデータを検証したうえで `tools/publish_toeic_three_model_results.ps1` からコピーします。

**Claudeの実測値がGitHub上に存在しない段階で数値を手入力しないこと。** `06_three_model_results_summary.json` と `11_three_model_report.md` を数値のSource of Truthとします。

## 正式成果物

| ファイル | 役割 |
|---|---|
| `00_validation_report.json` | 入力2700行、各モデル900行、15 prompts × 30 intents × 2 conditionsの検証 |
| `01_three_model_integrated_table.csv` | モデル別・3モデル平均の統合表 |
| `02_model_level_statistical_tests.csv` | 主要推論。30 intent平均を1プロンプト単位として15ペアでWilcoxon検定 |
| `03_prompt_level_statistical_tests.csv` | 15 prompts × 3 models = 45比較の補助分析 |
| `04_prompt_by_model_recovery.csv` | プロンプト別回復量 |
| `05_three_model_paired_rows.csv` | 1350対応ペア |
| `06_three_model_results_summary.json` | 最終結果サマリー |
| `07_three_model_initial_vs_optimized.png` | 3モデルの初期 vs 最適化後 |
| `08_three_model_recovery.png` | 3モデルの回復量比較 |
| `09_prompt_recovery_heatmap.png` | プロンプト×モデルの回復量ヒートマップ |
| `10_three_model_results.xlsx` | 全分析表をまとめたExcel |
| `11_three_model_report.md` | 日本語分析レポート |

## ポスター用図表

`ポスター用図表/` には、最終版として使う図だけを番号付きで集約します。

1. `01_3モデル_初期vs最適化.png`
2. `02_3モデル_回復量.png`
3. `03_3モデル_プロンプト別回復ヒートマップ.png`
4. `04_GPT5_長文vs短文.png`
5. `05_プロンプト収束.png`
6. `06_英語先行研究_vs_日本語TOEIC_主要傾向比較.svg`
   - 対応データ: `06_英語先行研究_vs_日本語TOEIC_主要傾向比較.csv`

1〜3はClaude込みの3モデル版です。4〜5は旧2モデルフォルダで生成済みですが、それぞれGPT-5単独のshort-query transfer、モデル非依存のprompt convergenceなので補助分析として継続使用します。

6は、先行研究と本研究の双方で数値を対応できるGPT-5 / Geminiについて、「人手の初期指示 → 最適化後」の変化を並べたポスター用比較図です。**研究間でデータ・クエリ・モデル設定が異なるため、絶対値の大小ではなく、悪化から0付近へ回復する変化方向を比較します。**

## 旧グラフとの区別

`../2026-08-07_OpenAI_Gemini_Full結果/07_initial_vs_optimized.png` はGPT-5 + Geminiのみの旧版です。3モデル公開後は、モデル比較には本フォルダの `07_three_model_initial_vs_optimized.png` を使用してください。

## 結果の表現

`rank_improvement = original rank - rewritten rank`。

最適化後平均が0未満である場合、結論は「原文より順位が上昇」ではなく、**「人手で設計した初期プロンプトによる順位悪化が、メタ最適化によって大幅に緩和された」**とします。
