import { Link } from 'react-router';
import {
  PiFoldersBold,
  PiNotePencilBold,
  PiTrayBold,
  PiTreeStructureBold,
} from 'react-icons/pi';

type Tab = 'my' | 'forms' | 'procedures' | 'inbox';

const tabs: {
  id: Tab;
  to: string;
  label: string;
  description: string;
  icon: typeof PiNotePencilBold;
}[] = [
  {
    id: 'my',
    to: '/patchform/my',
    label: 'マイ手続き',
    description: '自分の手続きを進める',
    icon: PiFoldersBold,
  },
  {
    id: 'forms',
    to: '/patchform',
    label: 'フォーム作成',
    description: '入力画面を作る',
    icon: PiNotePencilBold,
  },
  {
    id: 'procedures',
    to: '/patchform/procedures',
    label: '手続きを公開',
    description: '公開して、受付可能にする',
    icon: PiTreeStructureBold,
  },
  {
    id: 'inbox',
    to: '/patchform/inbox',
    label: '申請受付',
    description: '受付した内容を見る',
    icon: PiTrayBold,
  },
];

export const PatchformSubnav = ({ current }: { current: Tab }) => (
  <nav
    className='grid grid-cols-[repeat(auto-fit,minmax(calc(140/16*1rem),1fr))] gap-2'
    aria-label='フォームの画面'
  >
    {tabs.map((t) => {
      const selected = current === t.id;
      const Icon = t.icon;
      return (
        <Link
          key={t.id}
          to={t.to}
          aria-current={selected ? 'page' : undefined}
          className={`flex flex-col items-center gap-1 rounded-8 border px-2 pt-3 pb-3 text-center hover:border-transparent hover:bg-solid-gray-50 hover:outline-2 hover:outline-black hover:outline-solid lg:px-3 ${
            selected ? 'border-blue-900 bg-blue-50' : 'border-solid-gray-420 bg-white'
          }`}
        >
          <Icon aria-hidden={true} className='size-6 text-solid-gray-900' />
          <span className='text-dns-16B-130 text-pretty text-solid-gray-900'>{t.label}</span>
          <span className='text-dns-14N-130 text-pretty text-solid-gray-700'>{t.description}</span>
        </Link>
      );
    })}
  </nav>
);
