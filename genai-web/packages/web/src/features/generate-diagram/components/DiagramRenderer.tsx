import { Tab, TabGroup, TabList, TabPanel, TabPanels } from '@headlessui/react';
import { useRef } from 'react';
import { LuNetwork } from 'react-icons/lu';
import { VscCode } from 'react-icons/vsc';
import { CloseIcon, HamburgerMenuButton } from '@/components/ui/dads/HamburgerMenuButton';
import { NotebookSourceHandoff } from '@/open-genai/notebook/NotebookSourceHandoff';
import { saveDiagramFiles } from '@/open-genai/notebook/notebookMedia';
import { DownloadButton } from './DownloadButton';
import { Markdown } from './Markdown';
import { Mermaid } from './Mermaid';

const tabStyles = `
  flex items-center px-2 py-2.5 text-solid-gray-800
  first:rounded-l-4 last:rounded-r-4
  hover:underline hover:underline-offset-[calc(3/16*1rem)] 
  data-selected:bg-solid-gray-800 data-selected:font-700 data-selected:text-white data-selected:hover:no-underline
  focus-visible:outline-solid focus-visible:outline-4 focus-visible:outline-offset-[calc(2/16*1rem)] focus-visible:outline-black focus-visible:ring-[calc(2/16*1rem)] focus-visible:ring-yellow-300
`;

interface DiagramRendererProps {
  code: string;
}

export const DiagramRenderer = (props: DiagramRendererProps) => {
  const { code } = props;

  const zoomDialog = useRef<HTMLDialogElement>(null);

  return (
    <>
      <TabGroup>
        <div className='relative flex flex-col'>
          {/* ダイアグラム図の上のヘッダー */}
          <div className='mb-3 flex flex-row justify-between gap-1'>
            <div className='flex gap-1'>
              <DownloadButton type='SVG' code={code} />
              <DownloadButton type='PNG' code={code} />
              <NotebookSourceHandoff
                titlePrefix='図'
                label='ノートブックで扱う'
                commit={(sessionId) => saveDiagramFiles(sessionId, code, code)}
              />
            </div>
            <TabList className='flex cursor-pointer rounded-4 border bg-white text-oln-16N-100'>
              <Tab className={tabStyles}>
                <LuNetwork aria-hidden={true} className='mr-1.5 text-base' />
                図を表示
              </Tab>
              <Tab className={tabStyles}>
                <VscCode aria-hidden={true} className='mr-1.5 text-base' />
                コードを表示
              </Tab>
            </TabList>
          </div>

          {/* ダイアグラム図の描画部分 */}
          <TabPanels className='relative'>
            <TabPanel>
              <Mermaid code={code} handler={() => zoomDialog.current?.showModal()} />
            </TabPanel>
            <TabPanel>
              <Markdown>{['```mermaid', code, '```'].join('\n')}</Markdown>
            </TabPanel>
          </TabPanels>
        </div>
      </TabGroup>

      {/* ズーム時 */}
      <dialog
        className='m-auto h-[90%] w-[90%] overflow-visible rounded-8 border border-transparent bg-white px-6 py-4 shadow-2 backdrop:bg-opacity-gray-300 forced-colors:backdrop:bg-[#000b]'
        ref={zoomDialog}
      >
        <div className='flex h-full w-full flex-col rounded-8 bg-white'>
          <div className='flex justify-end px-4 py-3'>
            <HamburgerMenuButton
              className='p-1'
              onClick={() => {
                zoomDialog.current?.close();
              }}
            >
              <CloseIcon className='flex-none' />
              閉じる
            </HamburgerMenuButton>
          </div>
          <div className='flex-1 overflow-auto px-8 pb-8'>
            <Mermaid isZoom={true} code={code} />
          </div>
        </div>
      </dialog>
    </>
  );
};
