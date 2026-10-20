# 私有开发与公开版本发布

## 远程仓库约定

- `origin`：私有 Git 仓库，日常拉取和推送的默认目标。
- `github`：GitHub 发布仓库，只在版本人工验收后同步分支和指定版本标签。
- 实际服务器地址、账号、凭据和个人信息匹配词只保存在本机 Git 配置、凭据管理器或禅道服务端，不写入项目文件。

当前工作副本已设置默认远程和匿名身份。其他工作副本需自行添加这两个远程，并执行以下配置：

```bash
git config --local user.name 'BabelDoc contributors'
git config --local user.email ''
git config --local remote.pushDefault origin
git config --local push.default simple
git config --local branch.main.remote origin
git config --local branch.main.merge refs/heads/main
git config --local core.hooksPath scripts/git-hooks
```

使用 `git config --local --add privacy.forbiddenLiteral '待拦截的实际文本'` 分别配置个人账号、邮箱、域名和本机用户路径；这些值不提交。认证通过本机凭据管理器配置，勿将密码或 Token 写入远程 URL。

## 禅道中的日常流程

1. 创建 BabelDoc 产品，录入需求并评审；创建项目和迭代，拆分开发任务。
2. 在禅道的代码库管理入口关联私有 Git 仓库，按当前版本界面配置访问凭据、默认分支和提交同步。确认禅道能看到提交历史；仅推送 Git 不等于完成禅道关联。
3. 从 `main` 创建任务分支，开发后推送私有仓库。提交说明使用禅道中真实存在的对象编号，例如 `task#123 feat: add validation`、`bug#456 fix: handle cancellation`、`story#789 feat: improve progress`。文档中的 REQ/BUG 编号与禅道对象 ID 分开记录，不直接假定相等。
4. 开发记录同步更新需求与 Bug 文档；任务完成后创建版本并提测，记录测试结果、修复 Bug，经过人工验收后再将对应需求标记为已完成。
5. 验收通过后创建发布记录，关联需求、Bug 和版本标签，再同步 GitHub。

代码库菜单因版本或权限而异；关联语法参见[禅道 Git 集成说明](https://www.zentao.net/book/zentaopms/207.html)。首次关联后应检查一个真实任务是否出现提交记录，再依赖自动关联。

```bash
git switch -c feature/task-123
# 完成修改并暂存后：
git commit -m 'task#123 feat: describe the change'
git push -u origin feature/task-123
```

合并到私有仓库的 `main` 后，日常只需 `git push`。不要为 GitHub 配置自动推送、额外 push URL 或镜像推送。

## 发布与隐私检查

```bash
git switch main
git pull --ff-only origin main
python3 scripts/check_git_privacy.py
# 将 VERSION 替换为本次通过验收的版本；已有标签不重复创建。
git tag -a VERSION -m 'Release VERSION'
git push origin main refs/tags/VERSION
BABELDOC_PUBLISH=1 git push --atomic github main:main refs/tags/VERSION:refs/tags/VERSION
```

上述 GitHub 命令只推送当前分支和指定标签，保留全部祖先提交；不会创建 GitHub Release 页面。若 GitHub 分支已变化导致拒绝推送，先 fetch 并审查差异，不强制覆盖。

推送钩子检查所推引用的完整可达历史，包括作者、提交者、标签作者、提交与标签说明及所有历史文件。只允许匿名身份，并拦截本机配置的个人信息文本；错误只报告对象编号，不输出命中内容。GitHub 还要求显式设置发布变量。

这些检查覆盖已配置的已知信息，不能识别所有未知个人信息、图片中的文字或所有密钥。发布前仍需人工审查新增文件和差异；GitHub 的仓库所有者及推送账号会由平台显示，匿名提交不能隐藏平台账号。钩子是本机保护，可被 `--no-verify` 绕过，其他克隆需单独安装配置。不要在提交说明中添加个人署名或 Co-authored-by 邮箱。
