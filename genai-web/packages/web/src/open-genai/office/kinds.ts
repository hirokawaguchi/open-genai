export const OFFICE_APPS = [
  {
    id: 'office-word',
    path: '/office/word',
    label: '文書',
    template: 'document.docx',
    description: 'Word 形式の文書を、ブラウザの中で開いて編集します。',
  },
  {
    id: 'office-excel',
    path: '/office/excel',
    label: '表計算',
    template: 'workbook.xlsx',
    description: 'Excel 形式のブックを、ブラウザの中で開いて編集します。',
  },
  {
    id: 'office-powerpoint',
    path: '/office/powerpoint',
    label: 'スライド',
    template: 'presentation.pptx',
    description: 'PowerPoint 形式のスライドを、ブラウザの中で開いて編集します。',
  },
] as const;

export type OfficeAppId = (typeof OFFICE_APPS)[number]['id'];

export const officeAppById = (id: string) => OFFICE_APPS.find((app) => app.id === id);

/** 書き出したファイルを開くオフィスアプリ。文書・表計算・スライド以外は null。 */
export const officePathForFormat = (format: string): string | null => {
  if (format === 'docx') return '/office/word';
  if (format === 'xlsx') return '/office/excel';
  if (format === 'pptx') return '/office/powerpoint';
  return null;
};
