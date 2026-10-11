import { useId } from 'react';
import { Link } from 'react-router';
import {
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  Breadcrumbs,
  BreadcrumbsLabel,
  breadcrumbLinkStyle,
} from './dads/Breadcrumbs';

type Item = {
  label: string;
  to?: string;
  onClick?: () => void;
};

type Props = {
  items: Item[];
  className?: string;
};

export const BreadcrumbsNav = ({ items, className }: Props) => {
  const labelId = useId();
  return (
    <Breadcrumbs aria-labelledby={labelId} className={className}>
      <BreadcrumbsLabel className='sr-only' id={labelId}>
        現在位置
      </BreadcrumbsLabel>
      <BreadcrumbList>
        {items.map((item, index) => {
          const isCurrent = index === items.length - 1;
          return (
            <BreadcrumbItem key={index} isCurrent={isCurrent}>
              {!isCurrent && item.to ? (
                <BreadcrumbLink asChild>
                  <Link to={item.to}>{item.label}</Link>
                </BreadcrumbLink>
              ) : !isCurrent && item.onClick ? (
                <button type='button' className={breadcrumbLinkStyle} onClick={item.onClick}>
                  {item.label}
                </button>
              ) : (
                item.label
              )}
            </BreadcrumbItem>
          );
        })}
      </BreadcrumbList>
    </Breadcrumbs>
  );
};
