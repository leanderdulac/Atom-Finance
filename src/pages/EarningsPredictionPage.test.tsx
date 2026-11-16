import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import EarningsPredictionPage from './EarningsPredictionPage';

const earningsPrediction = vi.fn();

vi.mock('../services/api', () => ({
  api: {
    earningsPrediction: (...args: unknown[]) => earningsPrediction(...args),
  },
}));

describe('EarningsPredictionPage validation', () => {
  beforeEach(() => {
    earningsPrediction.mockReset().mockResolvedValue({ analysis: 'ok' });
  });

  it('blocks submit on empty fields and names the invalid count', async () => {
    const user = userEvent.setup();
    render(<EarningsPredictionPage />);
    await user.click(screen.getByRole('button', { name: /gerar veredito/i }));
    expect(earningsPrediction).not.toHaveBeenCalled();
    // 14 current + 14 previous fields, all empty
    expect(await screen.findByText(/preencha 28 campo\(s\)/i)).toBeInTheDocument();
  });

  it('blocks a single non-numeric field instead of coercing to 0', async () => {
    const user = userEvent.setup();
    render(<EarningsPredictionPage />);
    await user.click(screen.getByRole('button', { name: /dados de simulação/i }));
    // Corrupt one field: type=number inputs still accept arbitrary text via paste
    const inputs = screen.getAllByLabelText(/receita líquida/i);
    await user.clear(inputs[0]);
    await user.type(inputs[0], 'abc');
    await user.click(screen.getByRole('button', { name: /gerar veredito/i }));
    expect(earningsPrediction).not.toHaveBeenCalled();
    expect(await screen.findByText(/preencha 1 campo\(s\)/i)).toBeInTheDocument();
  });

  it('submits parsed numbers once every field is valid', async () => {
    const user = userEvent.setup();
    render(<EarningsPredictionPage />);
    await user.click(screen.getByRole('button', { name: /dados de simulação/i }));
    await user.click(screen.getByRole('button', { name: /gerar veredito/i }));
    expect(earningsPrediction).toHaveBeenCalledTimes(1);
    const payload = earningsPrediction.mock.calls[0][0] as {
      current_period: Record<string, number>;
      previous_period: Record<string, number>;
    };
    expect(payload.current_period.revenue).toBe(105000);
    expect(payload.previous_period.revenue).toBe(100000);
    expect(Object.values(payload.current_period).every((v) => typeof v === 'number')).toBe(true);
  });
});
