# Graph Report - D:\projects\major\project  (2026-04-27)

## Corpus Check
- Large corpus: 534 files · ~1,825,354 words. Semantic extraction will be expensive (many Claude tokens). Consider running on a subfolder, or use --no-semantic to run AST-only.

## Summary
- 11842 nodes · 36927 edges · 94 communities detected
- Extraction: 63% EXTRACTED · 37% INFERRED · 0% AMBIGUOUS · INFERRED: 13530 edges (avg confidence: 0.5)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]
- [[_COMMUNITY_Community 16|Community 16]]
- [[_COMMUNITY_Community 17|Community 17]]
- [[_COMMUNITY_Community 18|Community 18]]
- [[_COMMUNITY_Community 19|Community 19]]
- [[_COMMUNITY_Community 20|Community 20]]
- [[_COMMUNITY_Community 21|Community 21]]
- [[_COMMUNITY_Community 22|Community 22]]
- [[_COMMUNITY_Community 23|Community 23]]
- [[_COMMUNITY_Community 24|Community 24]]
- [[_COMMUNITY_Community 25|Community 25]]
- [[_COMMUNITY_Community 26|Community 26]]
- [[_COMMUNITY_Community 27|Community 27]]
- [[_COMMUNITY_Community 28|Community 28]]
- [[_COMMUNITY_Community 29|Community 29]]
- [[_COMMUNITY_Community 30|Community 30]]
- [[_COMMUNITY_Community 31|Community 31]]
- [[_COMMUNITY_Community 32|Community 32]]
- [[_COMMUNITY_Community 33|Community 33]]
- [[_COMMUNITY_Community 34|Community 34]]
- [[_COMMUNITY_Community 35|Community 35]]
- [[_COMMUNITY_Community 36|Community 36]]
- [[_COMMUNITY_Community 37|Community 37]]
- [[_COMMUNITY_Community 38|Community 38]]
- [[_COMMUNITY_Community 39|Community 39]]
- [[_COMMUNITY_Community 40|Community 40]]
- [[_COMMUNITY_Community 41|Community 41]]
- [[_COMMUNITY_Community 42|Community 42]]
- [[_COMMUNITY_Community 43|Community 43]]
- [[_COMMUNITY_Community 44|Community 44]]
- [[_COMMUNITY_Community 45|Community 45]]
- [[_COMMUNITY_Community 46|Community 46]]
- [[_COMMUNITY_Community 47|Community 47]]
- [[_COMMUNITY_Community 48|Community 48]]
- [[_COMMUNITY_Community 49|Community 49]]
- [[_COMMUNITY_Community 50|Community 50]]
- [[_COMMUNITY_Community 51|Community 51]]
- [[_COMMUNITY_Community 52|Community 52]]
- [[_COMMUNITY_Community 53|Community 53]]
- [[_COMMUNITY_Community 54|Community 54]]
- [[_COMMUNITY_Community 55|Community 55]]
- [[_COMMUNITY_Community 56|Community 56]]
- [[_COMMUNITY_Community 57|Community 57]]
- [[_COMMUNITY_Community 58|Community 58]]
- [[_COMMUNITY_Community 59|Community 59]]
- [[_COMMUNITY_Community 60|Community 60]]
- [[_COMMUNITY_Community 61|Community 61]]
- [[_COMMUNITY_Community 62|Community 62]]
- [[_COMMUNITY_Community 63|Community 63]]
- [[_COMMUNITY_Community 64|Community 64]]
- [[_COMMUNITY_Community 65|Community 65]]
- [[_COMMUNITY_Community 66|Community 66]]
- [[_COMMUNITY_Community 67|Community 67]]
- [[_COMMUNITY_Community 68|Community 68]]
- [[_COMMUNITY_Community 69|Community 69]]
- [[_COMMUNITY_Community 70|Community 70]]
- [[_COMMUNITY_Community 71|Community 71]]
- [[_COMMUNITY_Community 72|Community 72]]
- [[_COMMUNITY_Community 73|Community 73]]
- [[_COMMUNITY_Community 74|Community 74]]
- [[_COMMUNITY_Community 75|Community 75]]
- [[_COMMUNITY_Community 76|Community 76]]
- [[_COMMUNITY_Community 77|Community 77]]
- [[_COMMUNITY_Community 78|Community 78]]
- [[_COMMUNITY_Community 79|Community 79]]
- [[_COMMUNITY_Community 80|Community 80]]
- [[_COMMUNITY_Community 81|Community 81]]
- [[_COMMUNITY_Community 82|Community 82]]
- [[_COMMUNITY_Community 83|Community 83]]
- [[_COMMUNITY_Community 84|Community 84]]
- [[_COMMUNITY_Community 85|Community 85]]
- [[_COMMUNITY_Community 86|Community 86]]
- [[_COMMUNITY_Community 87|Community 87]]
- [[_COMMUNITY_Community 88|Community 88]]
- [[_COMMUNITY_Community 89|Community 89]]
- [[_COMMUNITY_Community 90|Community 90]]
- [[_COMMUNITY_Community 91|Community 91]]
- [[_COMMUNITY_Community 92|Community 92]]
- [[_COMMUNITY_Community 93|Community 93]]

## God Nodes (most connected - your core abstractions)
1. `BaseChatModel` - 321 edges
2. `BrowserStateSummary` - 318 edges
3. `getValueByPath()` - 301 edges
4. `push()` - 301 edges
5. `map()` - 293 edges
6. `EnhancedDOMTreeNode` - 292 edges
7. `setValueByPath()` - 290 edges
8. `SystemMessage` - 280 edges
9. `BaseWatchdog` - 279 edges
10. `UserMessage` - 250 edges

## Surprising Connections (you probably didn't know these)
- `Return a matching open page, or None if no relevant page is found.` --uses--> `ChatGoogle`  [INFERRED]
  agents\browser\agent.py → agents\browser\browser_use\llm\google\chat.py
- `Element class for element operations.` --uses--> `BrowserSession`  [INFERRED]
  agents\browser\browser_use\actor\element.py → agents\browser\browser_use\browser\session.py
- `Mouse class for mouse operations.` --uses--> `BrowserSession`  [INFERRED]
  agents\browser\browser_use\actor\mouse.py → agents\browser\browser_use\browser\session.py
- `# TODO: Implement smooth movement with multiple steps if needed` --uses--> `BrowserSession`  [INFERRED]
  agents\browser\browser_use\actor\mouse.py → agents\browser\browser_use\browser\session.py
- `Handle decoding any unicode escape sequences embedded in a string (needed to ren` --uses--> `AgentHistoryList`  [INFERRED]
  agents\browser\browser_use\agent\gif.py → agents\browser\browser_use\agent\views.py

## Communities

### Community 0 - "Community 0"
Cohesion: 0.0
Nodes (124): ab(), addRunDependency(), addWordBreakOpportunity(), adhocExecTask(), assertClientRequestTaskCapability(), assertTaskCapability(), assertTaskHandlerCapability(), assertToolsCallTaskCapability() (+116 more)

### Community 1 - "Community 1"
Cohesion: 0.01
Nodes (602): AboutBlankWatchdog, About:blank watchdog for managing about:blank tabs with DVD screensaver., Show DVD screensaver on all about:blank pages only., Injects a DVD screensaver-style bouncing logo loading animation overlay into the, Ensures there's always exactly one about:blank tab with DVD screensaver., Handle browser stop request - stop creating new tabs., Handle browser stopped event., Check tabs when a new tab is created. (+594 more)

### Community 2 - "Community 2"
Cohesion: 0.02
Nodes (575): ABC, Extract likely local file paths from task text for upload whitelisting., If the user indicates the target page is already open, prepend strict         i, BaseChatModel, Allow this Protocol to be used in Pydantic models -> very useful to typesafe the, BaseChatModel, BaseModel, ainvoke() (+567 more)

### Community 3 - "Community 3"
Cohesion: 0.01
Nodes (110): ActivityDetector, recordUserActivity(), ActivityMonitor, initializeActivityMonitor(), recordGlobalActivity(), startGlobalActivityMonitoring(), stopGlobalActivityMonitoring(), ClearcutLogger (+102 more)

### Community 4 - "Community 4"
Cohesion: 0.01
Nodes (184): bfsFileSearch(), bfsFileSearchSync(), processDirEntries(), getReleaseChannel(), isNightly(), isPreview(), isStable(), formatCheckpointDisplayList() (+176 more)

### Community 5 - "Community 5"
Cohesion: 0.01
Nodes (420): agentSkill(), applyElicitationDefaults(), applyLLMRequestModifications(), applyTemplateToInitialMessages(), array(), assertAny(), attributes(), batchJobDestinationFromMldev() (+412 more)

### Community 6 - "Community 6"
Cohesion: 0.01
Nodes (267): BrowserAgent, _build_fallback_summary(), _clean_join_text(), _cleanup_background_processes_sync(), CLIAgent, CLIResponse, _close_shared_resources(), _collect_tool_error_messages() (+259 more)

### Community 7 - "Community 7"
Cohesion: 0.01
Nodes (113): ActivateSkillTool, ActivateSkillToolInvocation, AskUserInvocation, AskUserTool, calculateExactReplacement(), calculateFlexibleReplacement(), calculateRegexReplacement(), calculateReplacement() (+105 more)

### Community 8 - "Community 8"
Cohesion: 0.01
Nodes (314): acknowledge(), addDirectories(), addDirectory(), appendResourcePathToUrl(), applyFilterFilesOptions(), #applyStat(), assertInternal(), attemptSelfCorrection() (+306 more)

### Community 9 - "Community 9"
Cohesion: 0.01
Nodes (313): abort(), addAndCheck(), addEventListener(), agentCapabilities(), agentCard(), agentProvider(), analyzeContentChunksForLoop(), appendTaskOptions() (+305 more)

### Community 10 - "Community 10"
Cohesion: 0.01
Nodes (42): AgentEntry, BaseSettings, BROWSER_USE_CONFIG_DIR(), BROWSER_USE_EXTENSIONS_DIR(), BROWSER_USE_PROFILES_DIR(), BrowserProfileEntry, Config, create_default_config() (+34 more)

### Community 11 - "Community 11"
Cohesion: 0.01
Nodes (256): _addCheck(), addDeprecationNoticeToError(), alignCenter(), alignRight(), and(), asNumber(), asObjectCount(), asPromise() (+248 more)

### Community 12 - "Community 12"
Cohesion: 0.01
Nodes (52): AllowedPathChecker, CheckerRunner, ClassifierStrategy, CompositeStrategy, createPolicyEngineConfig(), filterSecurePolicyDirectories(), formatPolicyError(), getPolicyDirectories() (+44 more)

### Community 13 - "Community 13"
Cohesion: 0.01
Nodes (238): addDirectoryContext(), addHistory(), aggregateResults(), all2(), applyAvailabilityTransition(), applyClientConfig(), applyModelSelection(), applyToolConfigModifications() (+230 more)

### Community 14 - "Community 14"
Cohesion: 0.01
Nodes (221): __(), addChecker(), addConfigTask(), addHookChecker(), addInline(), addLineBreak(), adjascentGlobstarOptimize(), append() (+213 more)

### Community 15 - "Community 15"
Cohesion: 0.01
Nodes (70): DefaultArgumentProcessor, handleAtCommand(), parseAllAtCommands(), AtFileProcessor, BuiltinCommandLoader, drainStdin(), runExitCleanup(), runSyncCleanup() (+62 more)

### Community 16 - "Community 16"
Cohesion: 0.01
Nodes (124): CloudAuthConfig, load_from_file(), Cloud browser service integration for browser-use.  This module provides integ, Stop a cloud browser session.  		Args: 			session_id: Session ID to stop. If, Compatibility fallback when browser_use.sync is not available., Close the HTTP client and cleanup any active sessions., Client for browser-use cloud browser service., Create a new cloud browser instance. For full docs refer to https://docs.cloud.b (+116 more)

### Community 17 - "Community 17"
Cohesion: 0.02
Nodes (189): [ABORT2](), acquireMutex(), addListener(), addToNumericResult(), baggageEntryMetadataFromString(), body(), checkAndRecordIfNeeded(), checkMemoryThreshold() (+181 more)

### Community 18 - "Community 18"
Cohesion: 0.09
Nodes (108): on_ClickElementEvent(), Default browser action handlers using CDP., Type text to the page (whatever element currently has focus). 		This is used wh, Get modifiers, virtual key code, and base key for a character.  		Returns:, Get the proper key code for a character (like Playwright does)., Clear text field using multiple strategies, starting with the most reliable., Simple focus strategy: CDP first, then click if failed., Check if an element requires direct value assignment instead of character-by-cha (+100 more)

### Community 19 - "Community 19"
Cohesion: 0.02
Nodes (112): buildState(), clone(), ensureStoreShape(), getCurrentSession(), getSessionList(), normalizeSession(), nowIso(), readStore() (+104 more)

### Community 20 - "Community 20"
Cohesion: 0.03
Nodes (162): activateFallbackMode(), addDefaultFields(), addEvent(), bufferTelemetryEvent(), cacheGoogleAccount(), calculateExactReplacement(), calculateFlexibleReplacement(), calculateRegexReplacement() (+154 more)

### Community 21 - "Community 21"
Cohesion: 0.02
Nodes (160): addBorder(), appendRootPathToUrlIfNeeded(), buildExcludePatterns(), colFromString(), computeNewContent(), conflicts(), constructYamlFloat(), convertLegacyAgentOptions() (+152 more)

### Community 22 - "Community 22"
Cohesion: 0.02
Nodes (23): BaseLlmClient, GeminiClient, executeToolWithHooks(), extractMcpContext(), CoreToolScheduler, createErrorResponse(), FakeContentGenerator, AgentExecutionBlockedError (+15 more)

### Community 23 - "Community 23"
Cohesion: 0.02
Nodes (150): assertArray(), assertArrayBuffer(), assertArrayLike(), assertAsyncFunction(), assertAsyncGenerator(), assertAsyncGeneratorFunction(), assertAsyncIterable(), assertBigInt64Array() (+142 more)

### Community 24 - "Community 24"
Cohesion: 0.02
Nodes (148): addRemoteTask(), addSubModuleTask(), applyPatchTask(), applyReplacement(), assertAll(), assertConnected(), assertEnumCase(), assertRequestHandlerCapability() (+140 more)

### Community 25 - "Community 25"
Cohesion: 0.02
Nodes (20): ChatCompressionService, findCompressSplitPoint(), modelStringToModelConfigAlias(), truncateHistoryToBudget(), ChatRecordingService, ContextManager, sanitizeEnvironment(), shouldRedactEnvironmentVariable() (+12 more)

### Community 26 - "Community 26"
Cohesion: 0.02
Nodes (18): HookAggregator, HookEventHandler, HookPlanner, HookRegistry, HookRunner, getNotificationMessage(), HookSystem, toSerializableDetails() (+10 more)

### Community 27 - "Community 27"
Cohesion: 0.03
Nodes (45): We have switched all of our code from langchain to openai.types.chat.chat_comple, _fix_control_characters_in_json(), ParseFailedGenerationError, Extract JSON from model output, handling both plain JSON and code-block-wrapped, Fix control characters in JSON string values to make them valid JSON., try_parse_groq_failed_generation(), serialize(), _serialize_assistant_content() (+37 more)

### Community 28 - "Community 28"
Cohesion: 0.03
Nodes (124): acknowledgeAgent(), addAgentPolicy(), addRule(), addSkillsWithPrecedence(), applyHookOutputToInput(), applySubstitutions(), asFullyQualifiedTool(), checkModule() (+116 more)

### Community 29 - "Community 29"
Cohesion: 0.03
Nodes (24): A2AClientManager, extractMessageText(), extractPartsText(), extractPartText(), extractTaskText(), isDataPart(), isFilePart(), isTextPart() (+16 more)

### Community 30 - "Community 30"
Cohesion: 0.03
Nodes (114): abc(), addIssueToContext(), addNode(), allowLegacyEntity(), assertNever(), cleanup(), datetimeRegex(), decideAdditionalProperties() (+106 more)

### Community 31 - "Community 31"
Cohesion: 0.06
Nodes (102): appendMessage(), appendSystemNotice(), appendTerminalTranscript(), applySessionState(), archiveSession(), blobToBase64(), buildSessionSummary(), cancelVoiceCapture() (+94 more)

### Community 32 - "Community 32"
Cohesion: 0.03
Nodes (97): _anchor_to_rect(), _bbox_center_to_screen_coords(), _bbox_logical_dimensions(), _bbox_to_capture_pixel_box(), capture_active_window(), _clamp(), clear_screen(), clear_stop_request() (+89 more)

### Community 33 - "Community 33"
Cohesion: 0.03
Nodes (98): artifact(), assertNotificationCapability(), auth(), authInternal(), _authThenStart(), buildDiscoveryUrls(), _buildHeaders(), buildWellKnownPath() (+90 more)

### Community 34 - "Community 34"
Cohesion: 0.03
Nodes (47): Test the two-tier model system., run_model_intro_test(), VisualizationServer, _clear_between_steps(), Test: All Visual Suites (Box -> Points -> CUA CLI -> CUA Vision)  Runs a singl, _run_box_sequence(), _run_points_sequence(), run_test_all_visuals() (+39 more)

### Community 35 - "Community 35"
Cohesion: 0.03
Nodes (90): abortPlugin(), activateSkill(), add(), addStatusChangeListener(), addTrustChangeListener(), args(), asArray(), asStringArray() (+82 more)

### Community 36 - "Community 36"
Cohesion: 0.04
Nodes (15): awaitConfirmation(), handleExternalModification(), handleInlineModification(), notifyHooks(), resolveConfirmation(), waitForConfirmation(), handleMcpPolicyUpdate(), handleStandardPolicyUpdate() (+7 more)

### Community 37 - "Community 37"
Cohesion: 0.04
Nodes (78): assertError(), childCount(), childForFieldId(), childForFieldName(), childrenForFieldId(), childrenForFieldName(), childWithDescendant(), currentDepth() (+70 more)

### Community 38 - "Community 38"
Cohesion: 0.04
Nodes (75): aborted2(), addToolCalls(), applyInlineModify(), applyNonInteractiveMode(), cancelAll(), cancelAllQueued(), check(), checkPolicy() (+67 more)

### Community 39 - "Community 39"
Cohesion: 0.05
Nodes (23): detectIde(), detectIdeFromEnv(), isCloudShell(), isJetBrains(), verifyJetBrains(), verifyVSCode(), IdeClient, getConnectionConfigFromFile() (+15 more)

### Community 40 - "Community 40"
Cohesion: 0.05
Nodes (40): _build_payload(), _clear_screen(), Clear all visual elements on screen.    Args:       host (str, optional): Ser, get_client(), VisualizationClient, _build_payload(), _create_text(), _create_text_for_box() (+32 more)

### Community 41 - "Community 41"
Cohesion: 0.06
Nodes (4): MCPServerConfig, resolveClassifierModel(), resolveModel(), Storage

### Community 42 - "Community 42"
Cohesion: 0.05
Nodes (38): Enum, args_as_dict(), args_as_list(), BrowserChannel, BrowserConnectArgs, BrowserContextArgs, BrowserLaunchArgs, BrowserLaunchPersistentContextArgs (+30 more)

### Community 43 - "Community 43"
Cohesion: 0.06
Nodes (31): PromptRegistry, PromptProvider, getCoreSystemPrompt(), gitRepoKeepUserInformed(), mandateConfirm(), mandateContinueWork(), mandateExplainBeforeActing(), mandateSkillGuidance() (+23 more)

### Community 44 - "Community 44"
Cohesion: 0.06
Nodes (25): _build_minimal_attributes(), _get_inline_text(), _has_direct_text(), _serialize_children(), _serialize_document_node(), _serialize_iframe(), serialize_tree(), _build_compact_attributes() (+17 more)

### Community 45 - "Community 45"
Cohesion: 0.08
Nodes (46): addLiteral(), addText(), closeBlock(), closeList(), closeListItem(), closeTable(), closeTableCell(), closeTableRow() (+38 more)

### Community 46 - "Community 46"
Cohesion: 0.06
Nodes (37): allowEditorTypeInSandbox(), classifyGoogleError(), classifyValidationRequiredError(), determineRequestsReferrer(), escapeELispString(), find(), getDiffCommand(), getEditorCommand() (+29 more)

### Community 47 - "Community 47"
Cohesion: 0.07
Nodes (10): crawl(), toPosixPath(), AbortError, DirectoryFileSearch, FileSearchFactory, filter(), RecursiveFileSearch, Ignore (+2 more)

### Community 48 - "Community 48"
Cohesion: 0.15
Nodes (35): captureSegment(), charFromCodepoint(), _class(), composeNode(), escapedHexLen(), fromDecimalCode(), fromHexCode(), generateError() (+27 more)

### Community 49 - "Community 49"
Cohesion: 0.07
Nodes (13): _coerce_text(), get_assistant_log_dir(), get_assistant_log_path(), log_assistant_event(), _project_root(), get_model_configs(), get_personalization_config(), get_tts_active_bool() (+5 more)

### Community 50 - "Community 50"
Cohesion: 0.08
Nodes (31): captures(), descendantsOfType(), getActiveBaggage(), getActiveSpan(), getBaggage(), getChangedRanges(), getHistoryDir(), getIncludedRanges() (+23 more)

### Community 51 - "Community 51"
Cohesion: 0.08
Nodes (27): asFunction(), childLoggerName(), clone2(), createLogger(), extend(), filterFunction(), filterType(), first() (+19 more)

### Community 52 - "Community 52"
Cohesion: 0.1
Nodes (27): addErrorMessage(), addFormat(), addPattern(), emoji(), escapeLiteralCheckValue(), escapeNonAlphaNumeric(), parseAnyDef(), parseArrayDef() (+19 more)

### Community 53 - "Community 53"
Cohesion: 0.1
Nodes (19): _extract_transcript_text(), _get_headers(), _get_stt_url(), Speech-to-Text Integration - ElevenLabs API.  Provides short-form transcription, Transcribe a recorded audio clip with ElevenLabs Speech-to-Text., transcribe_audio_bytes(), _get_headers(), _get_tts_url() (+11 more)

### Community 54 - "Community 54"
Cohesion: 0.12
Nodes (21): cleanup_font_cache(), create_highlighted_screenshot(), create_highlighted_screenshot_async(), draw_bounding_box_with_text(), draw_enhanced_bounding_box_with_text(), get_cross_platform_font(), get_element_color(), get_viewport_info_from_cdp() (+13 more)

### Community 55 - "Community 55"
Cohesion: 0.13
Nodes (20): computeMergedSettings(), createEmptyWorkspace(), customDeepMerge(), getDefaultsFromSchema(), getSystemDefaultsPath(), getSystemSettingsPath(), getTrustedFoldersPath(), getUserSettingsDir() (+12 more)

### Community 56 - "Community 56"
Cohesion: 0.21
Nodes (12): cleanSummaryParser(), createListLogSummaryParser(), diffSummaryTask(), forEachLineWithContent(), getDiffParser(), lineBuilder(), logFormatFromCommand(), logTask() (+4 more)

### Community 57 - "Community 57"
Cohesion: 0.29
Nodes (10): _add_overlay_to_image(), create_history_gif(), _create_task_frame(), decode_unicode_escapes_to_utf8(), Handle decoding any unicode escape sequences embedded in a string (needed to ren, Create initial frame showing the task., Add step number and goal overlay to an image., Wrap text to fit within a given width.  	Args: 	    text: Text to wrap (+2 more)

### Community 58 - "Community 58"
Cohesion: 0.27
Nodes (10): _build_model(), _check_unsupported(), Converts a JSON Schema dict to a runtime Pydantic model for structured extractio, Convert a JSON Schema dict to a runtime Pydantic model.  	The schema must be `, Raise ValueError if the schema uses unsupported composition keywords., Recursively resolve a JSON Schema node to a Python type.  	Returns a Python ty, Build a pydantic model from an object-type JSON Schema node., _resolve_type() (+2 more)

### Community 59 - "Community 59"
Cohesion: 0.18
Nodes (11): applyTransformer(), brand(), createZodEnum(), default(), keyof(), "node_modules/@kwsites/file-exists/dist/src/index.js"(), "node_modules/teeny-request/node_modules/agent-base/dist/src/index.js"(), "node_modules/teeny-request/node_modules/https-proxy-agent/dist/agent.js"() (+3 more)

### Community 60 - "Community 60"
Cohesion: 0.31
Nodes (6): _cleanup_process(), _find_free_port(), _find_installed_browser_path(), _launch_browser(), on_BrowserLaunchEvent(), _wait_for_cdp_url()

### Community 61 - "Community 61"
Cohesion: 0.2
Nodes (0): 

### Community 62 - "Community 62"
Cohesion: 0.39
Nodes (8): handleArray(), handleAttrPresenceName(), handleAttrValueName(), handleNode(), handlePopElementNode(), handlePushElementNode(), handleTagName(), hp2Builder()

### Community 63 - "Community 63"
Cohesion: 0.5
Nodes (4): _format_conversation(), Save conversation history to file asynchronously., Format the conversation including messages and response., save_conversation()

### Community 64 - "Community 64"
Cohesion: 1.0
Nodes (1): Create an UpdateAgentTaskEvent from an Agent instance

### Community 65 - "Community 65"
Cohesion: 1.0
Nodes (1): Validate base64 file content size.

### Community 66 - "Community 66"
Cohesion: 1.0
Nodes (1): Create a CreateAgentOutputFileEvent from a file path

### Community 67 - "Community 67"
Cohesion: 1.0
Nodes (1): Validate screenshot URL or base64 content size.

### Community 68 - "Community 68"
Cohesion: 1.0
Nodes (1): Create a CreateAgentStepEvent from agent step data

### Community 69 - "Community 69"
Cohesion: 1.0
Nodes (1): Create a CreateAgentTaskEvent from an Agent instance

### Community 70 - "Community 70"
Cohesion: 1.0
Nodes (1): Create a CreateAgentSessionEvent from an Agent instance

### Community 71 - "Community 71"
Cohesion: 1.0
Nodes (1): Cannot open devtools when headless is True

### Community 72 - "Community 72"
Cohesion: 1.0
Nodes (1): Set a unique default downloads path if none is provided.

### Community 73 - "Community 73"
Cohesion: 1.0
Nodes (1): Return the extra launch CLI args as a dictionary.

### Community 74 - "Community 74"
Cohesion: 1.0
Nodes (1): Return the extra launch CLI args as a list of strings.

### Community 75 - "Community 75"
Cohesion: 1.0
Nodes (1): Validate user data dir is set to a non-default path.

### Community 76 - "Community 76"
Cohesion: 1.0
Nodes (1): Alias for use_cloud field for compatibility.

### Community 77 - "Community 77"
Cohesion: 1.0
Nodes (1): Convert large domain lists (>=100 items) to sets for O(1) lookup performance.

### Community 78 - "Community 78"
Cohesion: 1.0
Nodes (1): Copy old config window_width & window_height to window_size.

### Community 79 - "Community 79"
Cohesion: 1.0
Nodes (1): Warn when both storage_state and user_data_dir are set, as this can cause confli

### Community 80 - "Community 80"
Cohesion: 1.0
Nodes (1): If user is using default profile dir with a non-default channel, force-change it

### Community 81 - "Community 81"
Cohesion: 1.0
Nodes (1): Ensure proxy configuration is consistent.

### Community 82 - "Community 82"
Cohesion: 1.0
Nodes (1): Ensure highlight_elements and dom_highlight_elements are not both enabled, with

### Community 83 - "Community 83"
Cohesion: 1.0
Nodes (1): File extension (e.g. 'txt', 'md')

### Community 84 - "Community 84"
Cohesion: 1.0
Nodes (1): Sanitize a filename by replacing/removing invalid characters.  		- Replaces sp

### Community 85 - "Community 85"
Cohesion: 1.0
Nodes (1): Restore file system from serializable state at the exact same location

### Community 86 - "Community 86"
Cohesion: 1.0
Nodes (1): Automatically parse the text inside content, whether it's a string or a list of

### Community 87 - "Community 87"
Cohesion: 1.0
Nodes (1): Automatically parse the text inside content, whether it's a string or a list of

### Community 88 - "Community 88"
Cohesion: 1.0
Nodes (1): Automatically parse the text inside content, whether it's a string or a list of

### Community 89 - "Community 89"
Cohesion: 1.0
Nodes (1): Create the most optimized schema by flattening all $ref/$defs while preserving

### Community 90 - "Community 90"
Cohesion: 1.0
Nodes (1): Ensure all properties are required for OpenAI strict mode

### Community 91 - "Community 91"
Cohesion: 1.0
Nodes (1): Create Gemini-optimized schema, preserving explicit `required` arrays so Gemini

### Community 92 - "Community 92"
Cohesion: 1.0
Nodes (1): Include common directories so workspace-scoped tools (ls/glob/read/write)

### Community 93 - "Community 93"
Cohesion: 1.0
Nodes (1): True only when the request is primarily "start/run existing local server".

## Knowledge Gaps
- **332 isolated node(s):** `Extract likely local file paths from task text for upload whitelisting.`, `If the user indicates the target page is already open, prepend strict         i`, `Main function demonstrating mixed automation with Browser-Use and Playwright.`, `Find the latest huge edit on the current wikipedia page.`, `Main function demonstrating mixed automation with Browser-Use and Playwright.` (+327 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Community 64`** (1 nodes): `Create an UpdateAgentTaskEvent from an Agent instance`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 65`** (1 nodes): `Validate base64 file content size.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 66`** (1 nodes): `Create a CreateAgentOutputFileEvent from a file path`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 67`** (1 nodes): `Validate screenshot URL or base64 content size.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 68`** (1 nodes): `Create a CreateAgentStepEvent from agent step data`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 69`** (1 nodes): `Create a CreateAgentTaskEvent from an Agent instance`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 70`** (1 nodes): `Create a CreateAgentSessionEvent from an Agent instance`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 71`** (1 nodes): `Cannot open devtools when headless is True`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 72`** (1 nodes): `Set a unique default downloads path if none is provided.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 73`** (1 nodes): `Return the extra launch CLI args as a dictionary.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 74`** (1 nodes): `Return the extra launch CLI args as a list of strings.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 75`** (1 nodes): `Validate user data dir is set to a non-default path.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 76`** (1 nodes): `Alias for use_cloud field for compatibility.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 77`** (1 nodes): `Convert large domain lists (>=100 items) to sets for O(1) lookup performance.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 78`** (1 nodes): `Copy old config window_width & window_height to window_size.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 79`** (1 nodes): `Warn when both storage_state and user_data_dir are set, as this can cause confli`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 80`** (1 nodes): `If user is using default profile dir with a non-default channel, force-change it`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 81`** (1 nodes): `Ensure proxy configuration is consistent.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 82`** (1 nodes): `Ensure highlight_elements and dom_highlight_elements are not both enabled, with`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 83`** (1 nodes): `File extension (e.g. 'txt', 'md')`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 84`** (1 nodes): `Sanitize a filename by replacing/removing invalid characters.  		- Replaces sp`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 85`** (1 nodes): `Restore file system from serializable state at the exact same location`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 86`** (1 nodes): `Automatically parse the text inside content, whether it's a string or a list of`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 87`** (1 nodes): `Automatically parse the text inside content, whether it's a string or a list of`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 88`** (1 nodes): `Automatically parse the text inside content, whether it's a string or a list of`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 89`** (1 nodes): `Create the most optimized schema by flattening all $ref/$defs while preserving`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 90`** (1 nodes): `Ensure all properties are required for OpenAI strict mode`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 91`** (1 nodes): `Create Gemini-optimized schema, preserving explicit `required` arrays so Gemini`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 92`** (1 nodes): `Include common directories so workspace-scoped tools (ls/glob/read/write)`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 93`** (1 nodes): `True only when the request is primarily "start/run existing local server".`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `JARVIS Models - LLM integration and routing.` connect `Community 2` to `Community 1`, `Community 6`, `Community 16`, `Community 49`, `Community 53`, `Community 27`?**
  _High betweenness centrality (0.235) - this node is a cross-community bridge._
- **Why does `Config` connect `Community 10` to `Community 41`?**
  _High betweenness centrality (0.110) - this node is a cross-community bridge._
- **Why does `project` connect `Community 6` to `Community 49`, `Community 34`, `Community 19`, `Community 53`?**
  _High betweenness centrality (0.079) - this node is a cross-community bridge._
- **Are the 318 inferred relationships involving `BaseChatModel` (e.g. with `Page` and `Page class for page-level operations.`) actually correct?**
  _`BaseChatModel` has 318 INFERRED edges - model-reasoned connections that need verification._
- **Are the 316 inferred relationships involving `BrowserStateSummary` (e.g. with `MessageManager` and `Get emoji for a message type - used only for logging display`) actually correct?**
  _`BrowserStateSummary` has 316 INFERRED edges - model-reasoned connections that need verification._
- **What connects `Extract likely local file paths from task text for upload whitelisting.`, `If the user indicates the target page is already open, prepend strict         i`, `Main function demonstrating mixed automation with Browser-Use and Playwright.` to the rest of the system?**
  _332 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `Community 0` be split into smaller, more focused modules?**
  _Cohesion score 0.0 - nodes in this community are weakly interconnected._