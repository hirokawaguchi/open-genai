import { useCallback } from 'react';
import { Link, useLocation } from 'react-router';

const baseClassName =
  "flex min-h-11 items-center rounded-4 py-1 pr-2 pl-4 hover:bg-solid-gray-50 hover:underline hover:underline-offset-[calc(3/16*1rem)] focus-visible:bg-yellow-300 focus-visible:ring-[calc(2/16*1rem)] focus-visible:ring-yellow-300 focus-visible:outline-4 focus-visible:outline-offset-0 focus-visible:outline-black focus-visible:outline-solid focus-visible:ring-inset aria-[current='page']:bg-blue-100! aria-[current='page']:font-bold aria-[current='page']:text-blue-1000! aria-current:bg-blue-100! aria-current:font-bold aria-current:text-blue-1000!";

type MobileMenuItemLinkProps = {
  className?: string;
  label: string;
  to: string;
  state?: unknown;
  disableParentAriaCurrent?: boolean;
};

type MobileMenuItemButtonProps = {
  className?: string;
  label: string;
  onClick: () => void;
};

export const MobileMenuItemLink = (props: MobileMenuItemLinkProps) => {
  const { className, label, to, state, disableParentAriaCurrent } = props;
  const location = useLocation();

  const ariaCurrentValue = useCallback(() => {
    if (location.pathname === to) {
      return 'page';
    }
    if (!disableParentAriaCurrent && to !== '/' && location.pathname.startsWith(`${to}/`)) {
      return 'true';
    }
    return undefined;
  }, [location.pathname, to, disableParentAriaCurrent]);

  return (
    <Link
      className={`${baseClassName} ${className ?? ''}`}
      aria-current={ariaCurrentValue()}
      to={to}
      state={state}
    >
      <div className='flex w-full items-center justify-between'>
        <span>{label}</span>
      </div>
    </Link>
  );
};

export const MobileMenuItemButton = (props: MobileMenuItemButtonProps) => {
  const { className, label, onClick } = props;

  return (
    <button
      type='button'
      className={`${baseClassName} w-full text-left ${className ?? ''}`}
      onClick={onClick}
    >
      <div className='flex w-full items-center justify-between'>
        <span>{label}</span>
      </div>
    </button>
  );
};
