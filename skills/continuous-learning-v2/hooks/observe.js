#!/usr/bin/env node
/**
 * Continuous Learning v2 - Observation Hook (Node.js)
 *
 * Cross-platform alternative to observe.sh.
 * Captures tool use events for pattern analysis.
 *
 * Hook config (in ~/.claude/settings.json):
 *
 * If installed as a plugin, use ${CLAUDE_PLUGIN_ROOT}:
 * {
 *   "hooks": {
 *     "PreToolUse": [{
 *       "matcher": "*",
 *       "hooks": [{ "type": "command",
 *         "command": "node ${CLAUDE_PLUGIN_ROOT}/skills/continuous-learning-v2/hooks/observe.js pre"
 *       }]
 *     }],
 *     "PostToolUse": [{
 *       "matcher": "*",
 *       "hooks": [{ "type": "command",
 *         "command": "node ${CLAUDE_PLUGIN_ROOT}/skills/continuous-learning-v2/hooks/observe.js post"
 *       }]
 *     }]
 *   }
 * }
 */

const fs = require('fs')
const path = require('path')
const os = require('os')

const CONFIG_DIR = path.join(os.homedir(), '.claude', 'homunculus')
const DEFAULT_MAX_FILE_SIZE_MB = 10

/**
 * Load config.json from the skill directory.
 * @returns {object} Parsed config or defaults
 */
function loadConfig() {
    const configPath = path.join(
        __dirname, '..', 'config.json',
    )
    try {
        return JSON.parse(fs.readFileSync(configPath, 'utf8'))
    } catch {
        return {
            observation: {
                enabled: true,
                store_path: path.join(CONFIG_DIR, 'observations.jsonl'),
                max_file_size_mb: DEFAULT_MAX_FILE_SIZE_MB,
                capture_tools: [
                    'Edit', 'Write', 'Bash', 'Read', 'Grep', 'Glob',
                ],
                ignore_tools: ['TodoWrite'],
            },
        }
    }
}

/**
 * Resolve the observations file path from config.
 * @param {object} config
 * @returns {string} Absolute path to observations.jsonl
 */
function getObservationsPath(config) {
    const storePath = config.observation?.store_path
        || '~/.claude/homunculus/observations.jsonl'
    return storePath.replace('~', os.homedir())
}

/**
 * Ensure the parent directory of a file path exists.
 * @param {string} filePath
 */
function ensureDir(filePath) {
    const dir = path.dirname(filePath)
    if (!fs.existsSync(dir)) {
        fs.mkdirSync(dir, { recursive: true })
    }
}

/**
 * Check whether a tool should be captured.
 * @param {string} tool - Tool name
 * @param {object} config - Loaded config
 * @returns {boolean}
 */
function shouldCapture(tool, config) {
    const captureTools = config.observation?.capture_tools || []
    const ignoreTools = config.observation?.ignore_tools || []
    if (ignoreTools.includes(tool)) return false
    if (captureTools.length === 0) return true
    return captureTools.includes(tool)
}

/**
 * Archive observations file if it exceeds the size limit.
 * @param {string} obsPath - Path to observations.jsonl
 * @param {number} maxSizeMb - Maximum file size in MB
 */
function archiveIfNeeded(obsPath, maxSizeMb) {
    if (!fs.existsSync(obsPath)) return
    try {
        const stats = fs.statSync(obsPath)
        const sizeMb = stats.size / (1024 * 1024)
        if (sizeMb >= maxSizeMb) {
            const archiveDir = path.join(
                path.dirname(obsPath), 'observations.archive',
            )
            if (!fs.existsSync(archiveDir)) {
                fs.mkdirSync(archiveDir, { recursive: true })
            }
            const timestamp = new Date()
                .toISOString()
                .replace(/[:.]/g, '-')
                .slice(0, 19)
            const archiveName = `observations-${timestamp}.jsonl`
            fs.renameSync(obsPath, path.join(archiveDir, archiveName))
        }
    } catch {
        // Silently ignore archive errors
    }
}

/**
 * Main entry point.
 * Reads hook JSON from stdin, writes observation to JSONL file.
 */
async function main() {
    const phase = process.argv[2] || 'post'
    const config = loadConfig()

    if (!config.observation?.enabled) {
        process.exit(0)
    }

    // Check disabled flag
    const disabledPath = path.join(CONFIG_DIR, 'disabled')
    if (fs.existsSync(disabledPath)) {
        process.exit(0)
    }

    let data = ''
    process.stdin.on('data', (chunk) => {
        data += chunk
    })

    process.stdin.on('end', () => {
        try {
            const input = JSON.parse(data)
            const toolName = input.tool_name || input.tool || 'unknown'

            if (!shouldCapture(toolName, config)) {
                // Pass through without capturing
                process.stdout.write(data)
                return
            }

            const obsPath = getObservationsPath(config)
            ensureDir(obsPath)

            const maxSize = config.observation?.max_file_size_mb
                || DEFAULT_MAX_FILE_SIZE_MB
            archiveIfNeeded(obsPath, maxSize)

            const toolInput = input.tool_input || input.input || {}
            const toolOutput = input.tool_output || input.output || ''

            // Truncate large payloads
            const inputStr = typeof toolInput === 'object'
                ? JSON.stringify(toolInput).slice(0, 5000)
                : String(toolInput).slice(0, 5000)
            const outputStr = typeof toolOutput === 'object'
                ? JSON.stringify(toolOutput).slice(0, 5000)
                : String(toolOutput).slice(0, 5000)

            const observation = {
                timestamp: new Date().toISOString(),
                event: phase === 'pre' ? 'tool_start' : 'tool_complete',
                session: input.session_id
                    || process.env.CLAUDE_SESSION_ID
                    || 'unknown',
                tool: toolName,
            }

            if (phase === 'pre') {
                observation.input = inputStr
            } else {
                observation.output = outputStr
            }

            fs.appendFileSync(
                obsPath,
                JSON.stringify(observation) + '\n',
            )

            // Pass through original data for hook chain
            process.stdout.write(data)
        } catch {
            // On error, pass through original data
            if (data) process.stdout.write(data)
        }
    })
}

main()
