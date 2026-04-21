import React, { useEffect, useRef, useState } from 'react';
import { Autocomplete, Box, CircularProgress, TextField, Typography } from '@mui/material';
import { api } from '../services/api';

type SearchOption = {
  symbol: string;
  name?: string;
  source?: string;
  exchange?: string;
};

interface MarketTickerAutocompleteProps {
  label: string;
  value?: string;
  values?: string[];
  onChange?: (value: string) => void;
  onValuesChange?: (values: string[]) => void;
  multiple?: boolean;
  disabled?: boolean;
  helperText?: string;
}

const asOption = (item: any): SearchOption => ({
  symbol: String(item?.symbol || '').toUpperCase(),
  name: item?.name ? String(item.name) : undefined,
  source: item?.source ? String(item.source) : undefined,
  exchange: item?.exchange ? String(item.exchange) : undefined,
});

// Return ONLY the symbol — prevents MUI from resetting inputValue to "SYMBOL — Name"
const getOptionLabel = (option: any): string => {
  if (typeof option === 'string') return option.toUpperCase();
  return (option?.symbol || '').toUpperCase();
};

export default function MarketTickerAutocomplete({
  label,
  value,
  values,
  onChange,
  onValuesChange,
  multiple = false,
  disabled = false,
  helperText,
}: MarketTickerAutocompleteProps) {
  const [inputValue, setInputValue] = useState((value || '').toUpperCase());
  const [loading, setLoading] = useState(false);
  const [options, setOptions] = useState<SearchOption[]>([]);

  // Track the latest external value — used to detect parent-driven resets
  const externalValueRef = useRef((value || '').toUpperCase());

  useEffect(() => {
    if (!multiple) {
      const next = (value || '').toUpperCase();
      externalValueRef.current = next;
      // Only overwrite the input when the parent explicitly changes the value
      // (e.g. a clear button or a different page resets it), not on every keystroke.
      setInputValue((prev) => (prev === next ? prev : next));
    }
  }, [multiple, value]);

  useEffect(() => {
    const query = inputValue.trim();
    if (query.length < 1) {
      setOptions([]);
      return;
    }

    let active = true;
    setLoading(true);
    const timer = window.setTimeout(async () => {
      try {
        const response: any = await api.search(query);
        if (!active) return;
        const nextOptions = Array.isArray(response?.results)
          ? response.results.map(asOption).filter((item: SearchOption) => item.symbol)
          : [];
        setOptions(nextOptions);
      } catch {
        if (active) setOptions([]);
      } finally {
        if (active) setLoading(false);
      }
    }, 300);

    return () => {
      active = false;
      window.clearTimeout(timer);
      setLoading(false);
    };
  }, [inputValue]);

  return (
    <Autocomplete
      multiple={multiple}
      freeSolo
      disabled={disabled}
      filterSelectedOptions
      options={options}
      // Uncontrolled value — let MUI manage it internally to avoid reset loops
      inputValue={inputValue}
      onInputChange={(_, newValue, reason) => {
        if (reason === 'reset') {
          // MUI fired a programmatic reset; only accept it if it matches our intended symbol
          const sym = (newValue || '').toUpperCase();
          const isClean = !sym.includes('—');
          if (isClean) setInputValue(sym);
          // Never propagate 'reset' to parent — prevents ticker being overwritten
          return;
        }
        const upper = (newValue || '').toUpperCase();
        setInputValue(upper);
        // Sync to parent on every real keystroke (fixes freeSolo "Load" button not seeing typed value)
        if (!multiple) onChange?.(upper || externalValueRef.current);
      }}
      isOptionEqualToValue={(option: any, selected: any) => {
        const a = typeof option === 'string' ? option : option?.symbol;
        const b = typeof selected === 'string' ? selected : selected?.symbol;
        return (a || '').toUpperCase() === (b || '').toUpperCase();
      }}
      getOptionLabel={getOptionLabel}
      renderOption={(props, option) => (
        <li {...props} key={option.symbol}>
          <Box sx={{ display: 'flex', flexDirection: 'column' }}>
            <Typography variant="body2" fontWeight={600}>{option.symbol}</Typography>
            {option.name && option.name !== option.symbol && (
              <Typography variant="caption" color="text.secondary" sx={{ lineHeight: 1.2 }}>
                {option.name}
              </Typography>
            )}
          </Box>
        </li>
      )}
      onChange={(_, newValue: any) => {
        if (multiple) {
          const next = (newValue || [])
            .map((item: any) => (typeof item === 'string' ? item : item.symbol))
            .map((s: string) => s.toUpperCase())
            .filter(Boolean);
          onValuesChange?.(Array.from(new Set(next)));
          return;
        }
        const sym = typeof newValue === 'string'
          ? newValue.toUpperCase()
          : (newValue?.symbol || '').toUpperCase();
        if (sym) onChange?.(sym);
      }}
      renderInput={(params) => (
        <TextField
          {...params}
          label={label}
          helperText={helperText}
          InputProps={{
            ...params.InputProps,
            endAdornment: (
              <>
                {loading ? <CircularProgress color="inherit" size={18} sx={{ mr: 1 }} /> : null}
                {params.InputProps.endAdornment}
              </>
            ),
          }}
        />
      )}
    />
  );
}
