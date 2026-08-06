# E-GEO v2 先行研究PDFの正本情報

最終確認日：2026年8月6日

## 正本

- ファイル名：`E-GEOv2.pdf`
- 論文名：*E-GEO: A Testbed for Generative Engine Optimization in E-Commerce*
- arXiv：`2511.20867v2`
- ページ数：54
- PDFサイズ：1,748,033 bytes
- SHA-256：`8f19f19df929d9e798e70a902d844c70a552f4d13f830b63af1847b31475f38b`
- PDF metadata author：Puneet S. Bagga; Vivek F. Farias; Tamar Korkotashvili; Tianyi Peng; Yuhang Wu

PDF本体は会話添付／研究ライブラリ側で保管し、リポジトリには版情報とハッシュを記録する。本文や付録を再確認するときは、上記SHA-256と一致するPDFを使用する。

## 日本語TOEIC研究との主な照合箇所

| 論文箇所 | 照合内容 |
|---|---|
| Section 3 | query-blindな商品説明リライト、固定候補、順位改善量 |
| Section 4 | 1クエリ10商品、対象商品だけを書き換えて再順位付け |
| Section 5.2 | 15種類の初期リライト戦略 |
| Section 5.4 / Algorithm 1 | 複数Re-rankerのTrain結果、匿名ラベル、Validation選択、Testロック |
| Appendix A.1 | Dense上位30件からGPT-5 miniで関連商品10件を選択 |
| Appendix A.2 | temperature、seed、モデル役割、元順位キャッシュ |
| Appendix B.1 | 共通Re-ranker User Prompt |
| Appendix B.2 | モデルファミリー別System Prompt |
| Appendix B.3 | 初期User Prompt 15種 |
| Appendix B.5 | Cross-Engine Meta-optimizer Prompt |

## 研究上の位置付け

現在の日本語TOEIC研究は、先行研究の完全再現ではなく、次の中核を保存した**予算縮小型日本語追試＋短文クエリ転移拡張**である。

保存する中核：

- 候補商品と対象商品をリライト前に固定
- Rewriterへ評価クエリを渡さない
- 対象listingだけを書き換える
- 元順位－書換後順位を評価指標にする
- 複数Re-rankerのTrain結果からMeta-optimizerが次Promptを作る
- ValidationはPrompt選択専用
- TestはPrompt固定後のみ使用
- 未学習モデルで転移を評価

明示する縮小・変更・拡張：

- 1000／500／2000ではなく40／10／30
- 学習Re-ranker 4モデルではなく2モデル
- 1 epoch 10 batchesではなく4 batches
- 英語商品向け`all-MiniLM-L6-v2`ではなく、日本語対応の`paraphrase-multilingual-MiniLM-L12-v2`でDense Retrievalを行う
- GeminiとClaudeは費用制約によりProvider固有の短縮System Promptを使用する
- 日本語TOEIC教材ドメインへ変更する
- 先行研究で明示されるTest対象固定に加え、本研究ではTrain／Validationもseed 42で対象商品を固定し、Prompt間比較の乱数差を除く
- 同一リライトを使った長文対短文の追加転移評価を行う
- Claudeを実行しない段階では、提供元を完全に跨ぐHeld-out評価とは表現しない

これらは研究目的に沿った事前固定の変更であり、結果確認後に追加・変更しない。

## 実行前条件

正式Fullの前に必ず次を完了する。

1. `Validate`合格
2. 候補選定1件Smoke合格
3. 全Provider接続Smoke合格
4. 候補80件選定完了
5. 正式工程Smoke合格
6. Smoke実測費用によるFull予算判定合格
7. OpenAI・GoogleのProvider hard stopが有効

この条件を満たすまで、正式な有料Full実験は開始しない。
