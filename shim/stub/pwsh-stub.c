/*
 * pwsh.exe — тонкий PE-стаб для лончера FGOAC scooby под Wine.
 *
 * Зачем: сам шим — bash-скрипт, и он прекрасно запускается через CreateProcess
 * (проверено: Windows-питон и CreateProcessW из ctypes его запускают). Но .NET-лончер
 * для вызовов скриптов передаёт список хендлов (STARTUPINFOEX) и до не-PE цели это
 * не доходит: процесс «стартует», сразу выходит с нулём и наш шим не вызывается.
 * Поэтому на месте pwsh.exe стоит настоящий PE, а он уже запускает bash-шим тем
 * самым CreateProcess, который работает.
 *
 * Путь к bash-шиму берётся из файла рядом с exe (pwsh-stub.ini, строка "shim=..."),
 * иначе — из FGOA_SHIM_SCRIPT, иначе из встроенного при сборке значения.
 */
#include <windows.h>
#include <string.h>

#define BUFSIZE 32768

static char shim_path[MAX_PATH * 4] = FGOA_SHIM_SCRIPT;

static void ini_path(char *out, DWORD size) {
    char exe[MAX_PATH * 4];
    DWORD n = GetModuleFileNameA(NULL, exe, sizeof(exe));
    if (n == 0 || n >= sizeof(exe)) {
        return;
    }
    char *slash = exe + n;
    while (slash > exe && *slash != '\\' && *slash != '/') {
        slash--;
    }
    if (out != exe) {
        DWORD len = (DWORD)(slash - exe + 1);
        if (len < size) {
            memcpy(out, exe, len);
            out[len] = 0;
        }
    }
}

static void load_config(void) {
    char dir[MAX_PATH * 4];
    char file[MAX_PATH * 4];
    dir[0] = 0;
    ini_path(dir, sizeof(dir));
    if (!dir[0]) {
        return;
    }
    lstrcpynA(file, dir, sizeof(file));
    lstrcatA(file, "pwsh-stub.ini");
    HANDLE h = CreateFileA(file, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, 0, NULL);
    if (h == INVALID_HANDLE_VALUE) {
        return;
    }
    char buf[4096];
    DWORD read = 0;
    if (ReadFile(h, buf, sizeof(buf) - 1, &read, NULL) && read > 0) {
        buf[read] = 0;
        char *line = buf;
        while (*line) {
            char *end = line;
            while (*end && *end != '\r' && *end != '\n') {
                end++;
            }
            char saved = *end;
            *end = 0;
            if (!strncmp(line, "shim=", 5)) {
                lstrcpynA(shim_path, line + 5, sizeof(shim_path));
            }
            *end = saved;
            line = end;
            while (*line == '\r' || *line == '\n') {
                line++;
            }
        }
    }
    CloseHandle(h);
}

int main(void) {
    char *cmd = GetCommandLineA();
    char *rest = cmd;
    /* пропускаем имя нашего exe (оно может быть в кавычках) */
    while (*rest == ' ' || *rest == '\t') {
        rest++;
    }
    if (*rest == '"') {
        rest++;
        while (*rest && *rest != '"') {
            rest++;
        }
        if (*rest == '"') {
            rest++;
        }
    } else {
        while (*rest && *rest != ' ' && *rest != '\t') {
            rest++;
        }
    }

    load_config();

    char line[BUFSIZE];
    lstrcpynA(line, "\"", sizeof(line));
    lstrcatA(line, shim_path);
    lstrcatA(line, "\" ");
    lstrcatA(line, rest);

    STARTUPINFOA si;
    PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof(si));
    si.cb = sizeof(si);
    si.dwFlags = STARTF_USESTDHANDLES;
    /* отдаём bash-шиму наши же стандартные потоки: лончер их перенаправляет к себе */
    si.hStdInput = GetStdHandle(STD_INPUT_HANDLE);
    si.hStdOutput = GetStdHandle(STD_OUTPUT_HANDLE);
    si.hStdError = GetStdHandle(STD_ERROR_HANDLE);

    if (!CreateProcessA(NULL, line, NULL, NULL, TRUE, 0, NULL, NULL, &si, &pi)) {
        const char *msg = "pwsh-stub: cannot start the bash shim - check pwsh-stub.ini\r\n";
        DWORD written = 0;
        WriteFile(GetStdHandle(STD_ERROR_HANDLE), msg, lstrlenA(msg), &written, NULL);
        (void)GetLastError();
        return 127;
    }
    CloseHandle(pi.hThread);
    WaitForSingleObject(pi.hProcess, INFINITE);
    DWORD code = 0;
    GetExitCodeProcess(pi.hProcess, &code);
    CloseHandle(pi.hProcess);
    return (int)code;
}
