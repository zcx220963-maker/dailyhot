interface GetHostParams {
  purpose?: string;
}

export const getHost = ({ purpose }: GetHostParams = {}): string => {
  if (typeof window !== 'undefined') {
    // 浏览器侧：始终用当前 origin（走前端 API 代理，由 Next.js 服务端转发到后端）
    // 不要返回 NEXT_PUBLIC_GPTR_API_URL（可能是 Docker 内网地址如 http://backend:8001，浏览器无法解析）
    let { host } = window.location;
    const apiUrlInLocalStorage = localStorage.getItem("GPTR_API_URL");

    const urlParams = new URLSearchParams(window.location.search);
    const apiUrlInUrlParams = urlParams.get("GPTR_API_URL");

    if (apiUrlInLocalStorage) {
      return apiUrlInLocalStorage;
    } else if (apiUrlInUrlParams) {
      return apiUrlInUrlParams;
    } else if (purpose === 'langgraph-gui') {
      return host.includes('localhost') ? 'http%3A%2F%2F127.0.0.1%3A8123' : `https://${host}`;
    } else {
      // 返回当前 origin（如 http://localhost:3000），让请求走前端 /api 代理
      return window.location.origin;
    }
  }
  return '';
};