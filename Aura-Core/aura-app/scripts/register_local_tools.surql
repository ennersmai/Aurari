-- ============================================================================
-- REGISTER LOCAL TOOLS (write_file, edit_file, create_directory, delete_file,
--                       execute_code, workspace_info)
-- Run: surreal import --conn http://localhost:8000 --user root --pass root
--      --ns aura --db main scripts/register_local_tools.surql
-- ============================================================================

USE NS aura DB main;

-- ============================================================================
-- FILESYSTEM WRITE TOOLS
-- ============================================================================

CREATE skill:write_file SET
    name = "write_file",
    tool_name = "write_file",
    domain = "filesystem",
    created = time::now(),
    mastery_level = 1.0,
    skill_type = "local_function",
    description_embedding = NONE,
    risk_level = "medium",
    definition = {
        name: "write_file",
        description: "Write content to a file. Creates the file if it doesn't exist, or overwrites if it does. Creates parent directories automatically.",
        inputSchema: {
            type: "object",
            properties: {
                path: { type: "string", description: "Path to the file to write" },
                content: { type: "string", description: "Content to write to the file" }
            },
            required: ["path", "content"]
        }
    },
    execution_config = {
        module: "aura.tools.filesystem",
        function: "write_file_run",
        tool_key: "write_file"
    };

CREATE skill:edit_file SET
    name = "edit_file",
    tool_name = "edit_file",
    domain = "filesystem",
    created = time::now(),
    mastery_level = 1.0,
    skill_type = "local_function",
    description_embedding = NONE,
    risk_level = "medium",
    definition = {
        name: "edit_file",
        description: "Edit a file by replacing a specific string with new content. Useful for targeted modifications without rewriting the entire file.",
        inputSchema: {
            type: "object",
            properties: {
                path: { type: "string", description: "Path to the file to edit" },
                old_string: { type: "string", description: "The exact string to find and replace" },
                new_string: { type: "string", description: "The replacement string" },
                replace_all: { type: "boolean", description: "Replace all occurrences (default: false)", default: false }
            },
            required: ["path", "old_string", "new_string"]
        }
    },
    execution_config = {
        module: "aura.tools.filesystem",
        function: "edit_file_run",
        tool_key: "edit_file"
    };

CREATE skill:create_directory SET
    name = "create_directory",
    tool_name = "create_directory",
    domain = "filesystem",
    created = time::now(),
    mastery_level = 1.0,
    skill_type = "local_function",
    description_embedding = NONE,
    risk_level = "low",
    definition = {
        name: "create_directory",
        description: "Create a new directory, including any necessary parent directories.",
        inputSchema: {
            type: "object",
            properties: {
                path: { type: "string", description: "Path of the directory to create" }
            },
            required: ["path"]
        }
    },
    execution_config = {
        module: "aura.tools.filesystem",
        function: "create_directory_run",
        tool_key: "create_directory"
    };

CREATE skill:delete_file SET
    name = "delete_file",
    tool_name = "delete_file",
    domain = "filesystem",
    created = time::now(),
    mastery_level = 1.0,
    skill_type = "local_function",
    description_embedding = NONE,
    risk_level = "high",
    definition = {
        name: "delete_file",
        description: "Delete a file or empty directory. Will NOT delete non-empty directories for safety.",
        inputSchema: {
            type: "object",
            properties: {
                path: { type: "string", description: "Path to the file or empty directory to delete" }
            },
            required: ["path"]
        }
    },
    execution_config = {
        module: "aura.tools.filesystem",
        function: "delete_file_run",
        tool_key: "delete_file"
    };

-- ============================================================================
-- CODE EXECUTION TOOLS
-- ============================================================================

CREATE skill:execute_code SET
    name = "execute_code",
    tool_name = "execute_code",
    domain = "code_execution",
    created = time::now(),
    mastery_level = 1.0,
    skill_type = "local_function",
    description_embedding = NONE,
    risk_level = "high",
    definition = {
        name: "execute_code",
        description: "Execute code in a sandboxed environment. Supports Python, Node.js, and shell scripts. Returns stdout, stderr, and exit code.",
        inputSchema: {
            type: "object",
            properties: {
                code: { type: "string", description: "The code to execute" },
                language: { type: "string", enum: ["python", "javascript", "shell", "powershell"], description: "Programming language", default: "python" },
                timeout: { type: "integer", description: "Execution timeout in seconds", default: 30 },
                working_dir: { type: "string", description: "Working directory (default: Aura workspace)", default: "" }
            },
            required: ["code"]
        }
    },
    execution_config = {
        module: "aura.tools.code_executor",
        function: "execute_code_run",
        tool_key: "execute_code"
    };

CREATE skill:workspace_info SET
    name = "workspace_info",
    tool_name = "workspace_info",
    domain = "code_execution",
    created = time::now(),
    mastery_level = 1.0,
    skill_type = "local_function",
    description_embedding = NONE,
    risk_level = "low",
    definition = {
        name: "workspace_info",
        description: "Get information about Aura's workspace directory — where code projects live.",
        inputSchema: {
            type: "object",
            properties: {}
        }
    },
    execution_config = {
        module: "aura.tools.code_executor",
        function: "workspace_info_run",
        tool_key: "workspace_info"
    };

-- ============================================================================
-- SEMANTIC TRIGGERS (for L1 fast routing)
-- ============================================================================

-- write_file triggers
CREATE semantic_trigger:write_file_1 SET
    phrase = "write a file",
    embedding = NONE,
    target_action = skill:write_file,
    confidence = 0.95;

CREATE semantic_trigger:write_file_2 SET
    phrase = "create a file",
    embedding = NONE,
    target_action = skill:write_file,
    confidence = 0.95;

CREATE semantic_trigger:write_file_3 SET
    phrase = "save to file",
    embedding = NONE,
    target_action = skill:write_file,
    confidence = 0.90;

-- edit_file triggers
CREATE semantic_trigger:edit_file_1 SET
    phrase = "edit the file",
    embedding = NONE,
    target_action = skill:edit_file,
    confidence = 0.95;

CREATE semantic_trigger:edit_file_2 SET
    phrase = "modify the file",
    embedding = NONE,
    target_action = skill:edit_file,
    confidence = 0.90;

CREATE semantic_trigger:edit_file_3 SET
    phrase = "replace in file",
    embedding = NONE,
    target_action = skill:edit_file,
    confidence = 0.95;

-- execute_code triggers
CREATE semantic_trigger:execute_code_1 SET
    phrase = "run this code",
    embedding = NONE,
    target_action = skill:execute_code,
    confidence = 0.95;

CREATE semantic_trigger:execute_code_2 SET
    phrase = "execute the script",
    embedding = NONE,
    target_action = skill:execute_code,
    confidence = 0.95;

CREATE semantic_trigger:execute_code_3 SET
    phrase = "run python",
    embedding = NONE,
    target_action = skill:execute_code,
    confidence = 0.90;

-- delete_file triggers
CREATE semantic_trigger:delete_file_1 SET
    phrase = "delete the file",
    embedding = NONE,
    target_action = skill:delete_file,
    confidence = 0.95;

CREATE semantic_trigger:delete_file_2 SET
    phrase = "remove the file",
    embedding = NONE,
    target_action = skill:delete_file,
    confidence = 0.90;
