import { Link } from 'react-router';
import { PiBookOpenBold } from 'react-icons/pi';
import { Disclosure, DisclosureSummary } from '@/components/ui/dads/Disclosure';
import { Button } from '@/components/ui/dads/Button';

export type CoachAction = {
  label: string;
  to?: string;
  onClick?: () => void;
};

export type CoachStep = {
  id: string;
  label: string;
  done: boolean;
  hint?: string;
  action?: CoachAction;
};

const StepAction = ({ action }: { action: CoachAction }) => {
  const button = (
    <Button
      type='button'
      variant='solid-fill'
      size='sm'
      onClick={action.to ? undefined : action.onClick}
    >
      {action.label}
    </Button>
  );
  if (action.to) {
    return (
      <Link to={action.to} className='inline-flex'>
        {button}
      </Link>
    );
  }
  return button;
};

export const PatchformProcedureCoach = ({
  title,
  lead,
  steps,
  defaultOpen = false,
}: {
  title: string;
  lead?: string;
  steps: CoachStep[];
  defaultOpen?: boolean;
}) => {
  const next = steps.find((s) => !s.done);

  return (
    <Disclosure
      className='rounded-8 border border-solid-gray-420 bg-solid-gray-50 px-4 py-3'
      aria-labelledby='pf-proc-coach-title'
      defaultOpen={defaultOpen}
    >
      <DisclosureSummary>
        <span className='flex flex-col gap-0.5 text-left'>
          <span id='pf-proc-coach-title' className='flex items-center text-std-16B-150'>
            <PiBookOpenBold className='mr-2 size-5 flex-none' />
            {title}（クリックで開閉）
          </span>
          <span className='text-dns-14N-130 font-normal text-solid-gray-700'>
            {next ? `次: ${next.label}` : '一通り完了しています'}
          </span>
        </span>
      </DisclosureSummary>
      {lead ? <p className='mt-3 text-std-16N-170 text-solid-gray-700'>{lead}</p> : null}
      <ol className='mt-3 flex flex-col gap-3'>
        {steps.map((step, index) => {
          const current = next?.id === step.id;
          return (
            <li
              key={step.id}
              className={`rounded-4 border bg-white px-3 py-3 ${
                current ? 'border-blue-900' : 'border-solid-gray-300'
              }`}
            >
              <div className='flex flex-wrap items-start gap-3'>
                <span
                  className={`mt-0.5 inline-flex size-6 shrink-0 items-center justify-center rounded-full text-dns-14B-130 ${
                    step.done
                      ? 'bg-blue-900 text-white'
                      : current
                        ? 'border border-blue-900 text-blue-900'
                        : 'border border-solid-gray-420 text-solid-gray-600'
                  }`}
                >
                  {step.done ? '済' : index + 1}
                </span>
                <div className='min-w-0 flex-1'>
                  <p className='text-std-16B-150'>{step.label}</p>
                  {step.hint ? (
                    <p className='mt-1 text-dns-16N-130 text-solid-gray-700'>{step.hint}</p>
                  ) : null}
                  {current && step.action ? (
                    <div className='mt-2'>
                      <StepAction action={step.action} />
                    </div>
                  ) : null}
                </div>
              </div>
            </li>
          );
        })}
      </ol>
    </Disclosure>
  );
};
