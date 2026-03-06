/**
 * @license
 * Copyright 2025 Google LLC
 * SPDX-License-Identifier: Apache-2.0
 */

/**
 * Stub: OAuth2 event emitter for auth events.
 * OAuth functionality removed for JARVIS integration.
 */

import { EventEmitter } from 'node:events';

class AuthEvents extends EventEmitter {}

export const authEvents = new AuthEvents();
