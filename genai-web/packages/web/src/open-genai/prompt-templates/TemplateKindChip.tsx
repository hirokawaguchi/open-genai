import { ChipLabel } from '@/components/ui/dads/ChipLabel';

type Props = {
  kind: string;
};

const styleOf = (kind: string): string => {
  switch (kind) {
    case '標準':
      return 'bg-blue-50 text-blue-900';
    case '共有':
      return 'bg-green-50 text-green-900';
    default:
      return 'bg-solid-gray-100 text-solid-gray-700';
  }
};

/** テンプレートの区分（標準／共有／個人）を表す小さなラベル。 */
export const TemplateKindChip = ({ kind }: Props) => {
  return <ChipLabel className={`min-h-6 px-2 py-0.5 text-oln-14N-100 ${styleOf(kind)}`}>{kind}</ChipLabel>;
};
