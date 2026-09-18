/*
 * pwsh.exe — PE-стаб для лончера FGOAC scooby под Wine.
 *
 * Зачем: сам шим — bash-скрипт, а Wine запускает его как *unix*-процесс. CreateProcessA
 * при этом отдаёт PE-процесс-обёртку, который завершается мгновенно, пока bash живёт
 * своей жизнью: WaitForSingleObject возвращается сразу, .NET-лончер видит «скрипт
 * кончился», снимает флаг serverConfiguring и сбрасывает статус на
 * «Server ports down/down/down» — хотя сервер в этот момент как раз поднимается.
 *
 * Поэтому стаб кладёт шиму в командную строку файл-отметку
 *
 *     --fgoa-done Z:\tmp\fgoa-shim-<pid>.exit
 *
 * и ждёт, пока файл появится: шим пишет туда свой код возврата (trap EXIT). Пока файла
 * нет, стаб жив, и лончер ждёт ровно столько, сколько работает хендлер. Потоки при этом
 * остаются прежними — лончер стримит наш вывод к себе, как и раньше.
 *
 * Путь к bash-шиму берётся из файла рядом с exe (pwsh-stub.ini, строка "shim=..."),
 * иначе — из FGOA_SHIM_SCRIPT, иначе из встроенного при сборке значения.
 */
#include <windows.h>
#include <string.h>

#define BUFSIZE 32768
#define POLL_MS 50
#define POLL_TRIES 36000          /* 30 минут: дольше ни один вызов лончера не живёт */

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
    DWORD len = (DWORD)(slash - exe + 1);
    if (len < size) {
        memcpy(out, exe, len);
        out[len] = 0;
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

static void append_ulong(char *out, unsigned long value) {
    char tmp[24];
    int n = 0;
    do {
        tmp[n++] = (char)('0' + (value % 10));
        value /= 10;
    } while (value && n < (int)sizeof(tmp));
    while (n > 0) {
        lstrcatA(out, (char[]){ tmp[--n], 0 });
    }
}

static int read_done_file(const char *path, int *value) {
    HANDLE h = CreateFileA(path, GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE,
                           NULL, OPEN_EXISTING, 0, NULL);
    if (h == INVALID_HANDLE_VALUE) {
        return 0;
    }
    char buf[64];
    DWORD read = 0;
    int found = 0;
    if (ReadFile(h, buf, sizeof(buf) - 1, &read, NULL) && read > 0) {
        buf[read] = 0;
        int v = -1;
        for (DWORD i = 0; i < read; i++) {
            if (buf[i] >= '0' && buf[i] <= '9') {
                v = (v < 0 ? 0 : v) * 10 + (buf[i] - '0');
            } else if (v >= 0) {
                break;
            }
        }
        if (v >= 0) {
            *value = v;
            found = 1;
        }
    }
    CloseHandle(h);
    return found;
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

    char done_path[MAX_PATH * 4];
    lstrcpynA(done_path, "Z:\\tmp\\fgoa-shim-", sizeof(done_path));
    append_ulong(done_path, (unsigned long)GetCurrentProcessId());
    lstrcatA(done_path, ".exit");
    DeleteFileA(done_path);          /* если остался от прошлого раза */

    char line[BUFSIZE];
    lstrcpynA(line, "\"", sizeof(line));
    lstrcatA(line, shim_path);
    lstrcatA(line, "\" --fgoa-done \"");
    lstrcatA(line, done_path);
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
    CloseHandle(pi.hProcess);

    /* ждём отметку шима: процесса-обёртки для этого мало, она умирает сразу */
    for (int i = 0; i < POLL_TRIES; i++) {
        int code = 0;
        if (read_done_file(done_path, &code)) {
            DeleteFileA(done_path);
            return code;
        }
        Sleep(POLL_MS);
    }

    {
        const char *msg = "pwsh-stub: the shim did not report completion within 30 minutes\r\n";
        DWORD written = 0;
        WriteFile(GetStdHandle(STD_ERROR_HANDLE), msg, lstrlenA(msg), &written, NULL);
    }
    return 1;
}
