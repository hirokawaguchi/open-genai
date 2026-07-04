import { describe, expect, it } from 'vitest';
import { isValidHttpsEndpointUrl } from '../../../../src/features/team-apps/utils/endpointUrl';

describe('isValidHttpsEndpointUrl', () => {
  it('accepts https endpoint without credentials', () => {
    expect(isValidHttpsEndpointUrl('https://example.com/invoke')).toBe(true);
  });

  it('accepts http endpoint for local Open GENAI microservices', () => {
    expect(isValidHttpsEndpointUrl('http://dify-app:8004/invoke')).toBe(true);
  });

  it('rejects endpoints with embedded credentials', () => {
    expect(isValidHttpsEndpointUrl('https://user:pass@example.com/invoke')).toBe(false);
  });

  it('rejects values with surrounding whitespace', () => {
    expect(isValidHttpsEndpointUrl(' https://example.com/invoke ')).toBe(false);
  });
});
