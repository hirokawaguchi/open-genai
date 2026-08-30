import type { IconType } from 'react-icons';
import {
  PiAlignLeftBold,
  PiArticleBold,
  PiBankBold,
  PiBuildingsBold,
  PiCalculatorBold,
  PiCalendarBlankBold,
  PiCalendarDotsBold,
  PiCalendarPlusBold,
  PiCaretCircleDownBold,
  PiCheckSquareBold,
  PiClockBold,
  PiEnvelopeSimpleBold,
  PiFileTextBold,
  PiGridFourBold,
  PiHashBold,
  PiHouseBold,
  PiIdentificationCardBold,
  PiImageBold,
  PiInfoBold,
  PiLockBold,
  PiMapPinBold,
  PiMinusBold,
  PiPaperclipBold,
  PiPenNibBold,
  PiPhoneBold,
  PiQrCodeBold,
  PiRadioButtonBold,
  PiScanBold,
  PiSlidersHorizontalBold,
  PiSquareBold,
  PiStarBold,
  PiTextTBold,
  PiUserBold,
} from 'react-icons/pi';

const ICONS: Record<string, IconType> = {
  text: PiTextTBold,
  textarea: PiAlignLeftBold,
  email: PiEnvelopeSimpleBold,
  phone: PiPhoneBold,
  number: PiHashBold,
  select: PiCaretCircleDownBold,
  radio: PiRadioButtonBold,
  checkbox: PiCheckSquareBold,
  slider: PiSlidersHorizontalBold,
  rating: PiStarBold,
  date: PiCalendarBlankBold,
  time: PiClockBold,
  'datetime-local': PiCalendarPlusBold,
  daterange: PiCalendarDotsBold,
  address_composite: PiHouseBold,
  user_info_composite: PiUserBold,
  company_info_composite: PiBuildingsBold,
  financial_institution_composite: PiBankBold,
  text_display: PiInfoBold,
  image_display: PiImageBold,
  divider: PiMinusBold,
  page_break: PiArticleBold,
  file: PiPaperclipBold,
  password: PiLockBold,
  calculated: PiCalculatorBold,
  mynumber: PiIdentificationCardBold,
  matrix_question: PiGridFourBold,
  signature_pad: PiPenNibBold,
  location: PiMapPinBold,
  qr_scanner: PiQrCodeBold,
  image_recognition: PiScanBold,
  document_reader: PiFileTextBold,
};

type Props = {
  type: string;
  className?: string;
};

export const CatalogTypeIcon = ({ type, className = 'size-5' }: Props) => {
  const Icon = ICONS[type] ?? PiSquareBold;
  return <Icon className={`flex-none ${className}`} aria-hidden={true} />;
};
