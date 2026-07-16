import { Artifact } from 'genai-web';

export const CITATION_MIME = 'text/x.open-genai.citation';

type Props = {
  artifacts?: Artifact[];
};

export const isCitationArtifact = (a: Artifact): boolean => a.mime_type === CITATION_MIME;

export const ExAppCitations = ({ artifacts }: Props) => {
  const citations = (artifacts ?? []).filter(isCitationArtifact);
  if (citations.length === 0) {
    return null;
  }

  return (
    <ul className='mt-3 space-y-2'>
      {citations.map((artifact, index) => (
        <li key={`${artifact.display_name}-${index}`}>
          <details className='group/citation rounded-8 border border-solid-gray-420 bg-white'>
            <summary
              className={`relative block cursor-pointer rounded-8 py-2.5 pr-3 pl-10 marker:[content:''] hover:bg-solid-gray-50 focus-visible:bg-yellow-300 focus-visible:ring-[calc(2/16*1rem)] focus-visible:ring-yellow-300 focus-visible:outline-4 focus-visible:outline-offset-[calc(2/16*1rem)] focus-visible:outline-black focus-visible:outline-solid [&::-webkit-details-marker]:hidden`}
            >
              <span
                className={`absolute top-3 left-3 inline-flex size-5 items-center justify-center text-blue-1000 group-open/citation:rotate-180`}
                aria-hidden={true}
              >
                <svg width='20' height='20' viewBox='0 0 20 20' fill='none'>
                  <path
                    d='M16.668 5.5L10.0013 12.1667L3.33464 5.5L2.16797 6.66667L10.0013 14.5L17.8346 6.66667L16.668 5.5Z'
                    fill='currentColor'
                  />
                </svg>
              </span>
              <span className='text-std-16N-170 text-blue-1000 underline underline-offset-[calc(3/16*1rem)]'>
                {artifact.display_name}
              </span>
            </summary>
            <div className='max-h-64 overflow-y-auto whitespace-pre-wrap break-words border-t border-solid-gray-420 px-3 py-3 text-dns-14N-130 text-solid-gray-800 leading-175'>
              {artifact.text || '（該当箇所のテキストがありません）'}
            </div>
          </details>
        </li>
      ))}
    </ul>
  );
};
