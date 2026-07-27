本仓库是 ChanQuant 量化交易系统的后端与 MCP Agent Gateway 代码库，**不包含任何前端样式源码**。前端是一个独立的私有仓库（ChanQuant-Vue），以预构建的 Nginx 镜像 `ghcr.io/brokermr810/ChanQuant-frontend` 形式通过 docker-compose 拉取并运行。因此在本仓库中不存在 CSS、SCSS、Tailwind 配置或设计令牌等前端样式文件。

- 前端源码位于单独的私有仓库，不在本仓库中；
- 本仓库仅通过 `docker-compose.yml` / `docker-compose.ghcr.yml` 引用已构建的前端镜像；
- 仅在 `docs/api/index.html` 和 `backend_api_python/app/services/portfolio_monitor.py` 中存在极少量内联 `<style>` 片段，属于文档/调试用途，不构成样式体系。

结论：`frontend_style` 不适用于本仓库。