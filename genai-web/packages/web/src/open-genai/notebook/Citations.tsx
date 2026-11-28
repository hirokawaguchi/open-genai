import { Disclosure, DisclosureSummary } from '@/components/ui/dads/Disclosure';
import { Markdown } from '@/components/Markdown';
import {
  citationNumber,
  formatNotebookMarkdown,
  sourceLabel,
  stripCitationMarks,
  usedCitations,
} from './formatMarkdown';
import type { NotebookCitation } from './types';

export const SourceList = ({
  citations,
  numbered = false,
  idPrefix,
}: {
  citations: NotebookCitation[];
  numbered?: boolean;
  idPrefix?: string;
}) => {
  if (!citations.length) return null;
  return (
    <div className='mt-2 flex flex-col gap-2'>
      {citations.map((c, i) => {
        const n = citationNumber(c);
        const id = idPrefix && n ? `${idPrefix}-${n}` : undefined;
        const label = sourceLabel(c);
        return (
          <Disclosure
            key={id || `${label}-${i}`}
            id={id}
            className='rounded-8 border border-solid-gray-300 px-3 py-2'
          >
            <DisclosureSummary className='w-full text-dns-14N-130 text-solid-gray-900'>
              {numbered && n ? `[${n}] ${label}` : label}
            </DisclosureSummary>
            {c.text && (
              <pre className='mt-2 max-h-40 overflow-auto whitespace-pre-wrap text-solid-gray-700'>
                {c.text}
              </pre>
            )}
          </Disclosure>
        );
      })}
    </div>
  );
};

export const ChatAnswer = ({
  content,
  citations,
  idPrefix,
}: {
  content: string;
  citations: NotebookCitation[];
  idPrefix: string;
}) => {
  const used = usedCitations(content, citations);
  return (
    <div className='mt-1 text-solid-gray-900'>
      <Markdown>{formatNotebookMarkdown(stripCitationMarks(content))}</Markdown>
      <SourceList citations={used} idPrefix={idPrefix} />
    </div>
  );
};
