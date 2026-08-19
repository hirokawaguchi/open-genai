import { Label } from '@/components/ui/dads/Label';
import { catalogTypeHelp } from '../labels';
import type { CatalogItem, FormComponent, VisibleWhenRule } from '../types';

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
  const rules: VisibleWhenRule[] = Array.isArray(c.visibleWhen)
    ? c.visibleWhen
    : c.visibleWhen
      ? [c.visibleWhen]
      : [];
  const setRules = (next: VisibleWhenRule[]) => {
    const cleaned = next.filter((r) => r.field);
    onChange({
      ...c,
      visibleWhen: cleaned.length === 0 ? undefined : cleaned.length === 1 ? cleaned[0] : cleaned,
    });
  };

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
      <div className='flex flex-col gap-2'>
        <Label size='sm'>表示条件</Label>
        <p className='text-dns-14N-130 text-solid-gray-700'>
          すべての条件を満たすときだけ表示します。隠れた必須項目は回答不要です。
        </p>
        {rules.map((rule, i) => {
          const mode = rule.in ? 'in' : 'eq';
          return (
            <div key={`${rule.field}-${i}`} className='grid gap-2 rounded-8 border border-solid-gray-300 p-3 md:grid-cols-2'>
              <div>
                <Label size='sm'>部品</Label>
                <select
                  className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2'
                  value={rule.field}
                  onChange={(e) => {
                    const next = [...rules];
                    next[i] = { ...rule, field: e.target.value };
                    setRules(next);
                  }}
                >
                  <option value=''>選択してください</option>
                  {siblings
                    .filter((x) => x.id !== c.id)
                    .map((x) => (
                      <option key={x.id} value={x.id}>
                        {x.label || x.id}
                      </option>
                    ))}
                </select>
              </div>
              <div>
                <Label size='sm'>比べ方</Label>
                <select
                  className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2'
                  value={mode}
                  onChange={(e) => {
                    const next = [...rules];
                    if (e.target.value === 'in') {
                      next[i] = {
                        field: rule.field,
                        in: rule.in ?? (rule.eq ? [rule.eq] : []),
                      };
                    } else {
                      next[i] = { field: rule.field, eq: rule.eq ?? (rule.in || []).join(',') };
                    }
                    setRules(next);
                  }}
                >
                  <option value='eq'>この値のとき</option>
                  <option value='in'>いずれかの値のとき</option>
                </select>
              </div>
              <div className='md:col-span-2'>
                <Label size='sm'>{mode === 'in' ? '値（カンマ区切り）' : '値'}</Label>
                <input
                  className='mt-1 w-full rounded-4 border border-solid-gray-420 px-3 py-2'
                  value={mode === 'in' ? (rule.in || []).join(',') : rule.eq || ''}
                  onChange={(e) => {
                    const next = [...rules];
                    next[i] =
                      mode === 'in'
                        ? {
                            field: rule.field,
                            in: e.target.value.split(',').map((s) => s.trim()).filter(Boolean),
                          }
                        : { field: rule.field, eq: e.target.value };
                    setRules(next);
                  }}
                />
              </div>
              <div>
                <button
                  type='button'
                  className='text-dns-16N-130 text-blue-900 underline'
                  onClick={() => setRules(rules.filter((_, j) => j !== i))}
                >
                  この条件を削除
                </button>
              </div>
            </div>
          );
        })}
        <button
          type='button'
          className='self-start text-std-16N-170 text-blue-900 underline'
          onClick={() => {
            const first = siblings.find((x) => x.id !== c.id);
            if (!first) return;
            setRules([...rules, { field: first.id, eq: '' }]);
          }}
        >
          条件を追加
        </button>
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
