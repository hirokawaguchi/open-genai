import { Checkbox } from '@/components/ui/dads/Checkbox';
import { Input } from '@/components/ui/dads/Input';
import { Label } from '@/components/ui/dads/Label';
import { SupportText } from '@/components/ui/dads/SupportText';
import type { KnowledgeTag } from './types';

type Props = {
  idPrefix: string;
  tags: KnowledgeTag[];
  /** チェック済みの既存タグ。 */
  selected: string[];
  onToggle: (tag: string) => void;
  /** 新規タグ（カンマ / セミコロン区切り）。 */
  newTagsText: string;
  onNewTagsText: (v: string) => void;
};

/** タグ入力（分割・重複除去）。既存の選択 + 新規テキストを合成する。 */
export const mergeTags = (selected: string[], newTagsText: string): string[] => {
  const fromText = newTagsText
    .replace(/;/g, ',')
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);
  const out: string[] = [];
  for (const t of [...selected, ...fromText]) {
    if (!out.includes(t)) out.push(t);
  }
  return out;
};

export const TagPicker = ({
  idPrefix,
  tags,
  selected,
  onToggle,
  newTagsText,
  onNewTagsText,
}: Props) => {
  return (
    <div className='flex flex-col gap-2'>
      <Label htmlFor={`${idPrefix}-new-tags`} size='sm'>
        タグ
      </Label>
      <SupportText>
        既存タグを選択、または新しいタグを入力（カンマ区切り）。タグ未付与の資料は検索対象外です。
      </SupportText>
      {tags.length > 0 && (
        <div className='flex flex-wrap gap-x-4 gap-y-1'>
          {tags.map((t) => (
            <Checkbox
              key={t.tag}
              size='sm'
              checked={selected.includes(t.tag)}
              onChange={() => onToggle(t.tag)}
            >
              {t.tag}
            </Checkbox>
          ))}
        </div>
      )}
      <Input
        id={`${idPrefix}-new-tags`}
        type='text'
        placeholder='新しいタグ（例: 総務, 例規）'
        value={newTagsText}
        onChange={(e) => onNewTagsText(e.target.value)}
        className='min-w-64 max-w-full'
      />
    </div>
  );
};
