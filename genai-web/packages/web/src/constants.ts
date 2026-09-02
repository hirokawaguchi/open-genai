// サービス名称（VITE_APP_TITLE。未設定時は Open GENAI）
export const APP_TITLE = (import.meta.env.VITE_APP_TITLE ?? 'Open GENAI').trim();

export const EXAPP_STATUS_OPTIONS = [
  { value: 'draft', label: '下書き' },
  { value: 'published', label: '公開' },
] as const;

export const MARKDOWN_EXAMPLE = `■ 見出し

# 見出し1
## 見出し2
### 見出し3
#### 見出し4
##### 見出し5
###### 見出し6

※見出し1は、AIアプリを作成した際の「名前」として表示されます。使い方の欄に見出しを記載する際は、見出し1は用いず「見出し2」から始めることを推奨します。

■ 順序なしリスト

- リスト
    - 子リスト
- リスト
- リスト

■ 順序付きリスト

1. リスト
    1. 子リスト
2. リスト
3. リスト

■ リンクテキスト

[デジタル庁デザインシステム専用サイト](https://design.digital.go.jp/)

※ URLを貼り付けると自動でリンクになります。
※ アクセシビリティ上の観点から [こちら](https://www.digital.go.jp/) のようにリンク先が判別できない表記ではなく、リンクテキストのみで遷移先の内容が理解できるようにしてください。（例：[デジタル庁ウェブサイト](https://www.digital.go.jp/)）

■ テーブル

| ヘッダーセル | ヘッダーセル | ヘッダーセル |
|------------|------------|------------|
| テキスト    | テキスト    | テキスト    |
| テキスト    | テキスト    | テキスト    |

■ ディスクロージャー（折りたたみ）

:::disclosure{title=タイトル}

トグルの内容

:::

■ 引用

> 引用テキスト
> 引用テキスト

■ インラインスタイル

**強調** 
*イタリック*
~~打ち消し~~  
\`コード\`

■ 区切り線

---

■ コードブロック

\`\`\`
const hello = () => {
  console.log("Hello World")
}
\`\`\``;
