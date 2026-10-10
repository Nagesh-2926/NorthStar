import '@testing-library/jest-dom/vitest';
import { afterEach } from 'vitest';
import { cleanup } from '@testing-library/react';
import axios from 'axios';

// Every test must supply an explicit adapter or mock the service module. A missed
// mock fails locally instead of sending an HTTP request to a running backend.
axios.defaults.adapter = async () => {
  throw new Error('Unexpected HTTP request in a mock-only frontend test.');
};

afterEach(() => cleanup());
