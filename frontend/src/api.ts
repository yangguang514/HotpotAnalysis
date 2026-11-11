export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

interface RequestOptions {
  method?: "GET" | "POST";
  body?: unknown;
}

export async function request<T>(
  path: string,
  token: string,
  options: RequestOptions = {},
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (token) headers.Authorization = `Bearer ${token}`;

  const response = await fetch(path, {
    method: options.method ?? "GET",
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });

  let data: Record<string, unknown>;
  try {
    data = await response.json() as Record<string, unknown>;
  } catch {
    throw new ApiError(`服务器返回了无法解析的响应（HTTP ${response.status}）`, response.status);
  }

  if (!response.ok) {
    const message = data.error ?? data.message;
    throw new ApiError(
      typeof message === "string" ? message : `请求失败（HTTP ${response.status}）`,
      response.status,
    );
  }

  return data as T;
}
