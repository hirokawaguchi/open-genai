import { Label } from '@/components/ui/dads/Label';
import { catalogTypeHelp } from '../labels';
import type { CatalogItem, FormComponent } from '../types';

type Props = {
  component: FormComponent;
  catalog: CatalogItem[];
  siblings: FormComponent[];
  onChange: (next: FormComponent) => void;
};

const IMI_PRESETS = [
  'ic:氏名',
  'ic:氏名カナ',
  'ic:住所',
  'ic:郵便番号',
  'ic:メールアドレス',
  'ic:電話番号',
  'ic:生年月日',
  'ic:法人番号',
];

export const ComponentSettings = ({ component: c, catalog, siblings, onChange }: Props) => {
  const meta = catalog.find((x) => x.type === c.type);
  const visibleWhen = !Array.isArray(c.visibleWhen) ? c.visibleWhen : undefined;

  return (
    <div className='flex flex-col gap-3'>
      {catalogTypeHelp(c.type, meta?.description) ? (
        <p className='text-dns-14N-130 text-solid-gray-700'>
          {catalogTypeHelp(c.type, meta?.description)}
        </p>
      ) : null}
      <div className='grid gap-3 md:grid-cols-2'>
        <div>
          <Label size='sm'>ラベル</Label>
          <input
            className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2'
            value={c.label}
            onChange={(e) => onChange({ ...c, label: e.target.value })}
          />
        </div>
        <div>
          <Label size='sm'>プレースホルダ</Label>
          <input
            className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2'
            value={c.placeholder || ''}
            onChange={(e) => onChange({ ...c, placeholder: e.target.value })}
          />
        </div>
      </div>
      <div className='flex flex-wrap gap-x-6 gap-y-2'>
        <label className='flex items-center gap-2 text-std-14N-160'>
          <input
            type='checkbox'
            checked={!!c.required}
            onChange={(e) => onChange({ ...c, required: e.target.checked })}
          />
          必須
        </label>
        <label className='flex items-center gap-2 text-std-14N-160'>
          <input
            type='checkbox'
            checked={!!c.hide_label}
            onChange={(e) => onChange({ ...c, hide_label: e.target.checked })}
          />
          回答画面でラベルを隠す
        </label>
      </div>
      {c.hide_label ? (
        <p className='text-dns-14N-130 text-solid-gray-700'>
          ラベルは編集・CSV では使います。回答者には見せません（読み上げ用には残します）。
        </p>
      ) : null}
      {c.type === 'matrix_question' && (
        <div className='grid gap-2 md:grid-cols-2'>
          <div>
            <Label size='sm'>行（改行区切り）</Label>
            <textarea
              className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2'
              rows={3}
              value={((c.properties?.rows as string[]) || []).join('\n')}
              onChange={(e) =>
                onChange({
                  ...c,
                  properties: {
                    ...c.properties,
                    rows: e.target.value.split('\n').map((s) => s.trim()).filter(Boolean),
                  },
                })
              }
            />
          </div>
          <div>
            <Label size='sm'>列（改行区切り）</Label>
            <textarea
              className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2'
              rows={3}
              value={((c.properties?.columns as string[]) || []).join('\n')}
              onChange={(e) =>
                onChange({
                  ...c,
                  properties: {
                    ...c.properties,
                    columns: e.target.value.split('\n').map((s) => s.trim()).filter(Boolean),
                  },
                })
              }
            />
          </div>
        </div>
      )}
      {c.type === 'text_display' && (
        <div>
          <Label size='sm'>説明文</Label>
          <textarea
            className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2'
            rows={3}
            value={String(c.properties?.text || '')}
            onChange={(e) => onChange({ ...c, properties: { ...c.properties, text: e.target.value } })}
          />
        </div>
      )}
      {c.type === 'image_display' && (
        <div>
          <Label size='sm'>画像 URL（https または data:image）</Label>
          <input
            className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2'
            value={String(c.properties?.src || '')}
            onChange={(e) => onChange({ ...c, properties: { ...c.properties, src: e.target.value } })}
          />
        </div>
      )}
      {c.type === 'calculated' && (
        <div>
          <Label size='sm'>計算式（例: {'{{qty}} * 100'}）</Label>
          <input
            className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2'
            value={String(c.properties?.formula || '')}
            onChange={(e) => onChange({ ...c, properties: { ...c.properties, formula: e.target.value } })}
          />
        </div>
      )}
      <div>
        <Label size='sm'>IMI 語彙（任意）</Label>
        <input
          className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2'
          list='pf-imi-presets'
          value={c.imi_type || ''}
          onChange={(e) => onChange({ ...c, imi_type: e.target.value })}
          placeholder='例: ic:住所'
        />
        <datalist id='pf-imi-presets'>
          {IMI_PRESETS.map((v) => (
            <option key={v} value={v} />
          ))}
        </datalist>
      </div>
      <div className='grid gap-2 md:grid-cols-2'>
        <div>
          <Label size='sm'>表示条件の部品</Label>
          <select
            className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2'
            value={visibleWhen?.field || ''}
            onChange={(e) =>
              onChange({
                ...c,
                visibleWhen: e.target.value
                  ? { field: e.target.value, eq: visibleWhen?.eq || '' }
                  : undefined,
              })
            }
          >
            <option value=''>常に表示</option>
            {siblings
              .filter((x) => x.id !== c.id)
              .map((x) => (
                <option key={x.id} value={x.id}>
                  {x.label || x.id}
                </option>
              ))}
          </select>
        </div>
        {visibleWhen?.field ? (
          <div>
            <Label size='sm'>この値のとき表示</Label>
            <input
              className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2'
              value={visibleWhen.eq || ''}
              onChange={(e) => onChange({ ...c, visibleWhen: { ...visibleWhen, eq: e.target.value } })}
            />
          </div>
        ) : null}
      </div>
      {meta?.has_options && (
        <div>
          <Label size='sm'>選択肢（改行区切り）</Label>
          <textarea
            className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2'
            rows={3}
            value={(c.properties?.options || []).join('\n')}
            onChange={(e) =>
              onChange({
                ...c,
                properties: {
                  ...c.properties,
                  options: e.target.value.split('\n').map((s) => s.trim()).filter(Boolean),
                },
              })
            }
          />
        </div>
      )}
    </div>
  );
};
