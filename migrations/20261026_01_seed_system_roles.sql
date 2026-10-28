-- 阶段 8：补齐管理后台使用的系统角色。
-- 可重复执行；不会删除、改写或重新绑定现有用户角色。
INSERT INTO kh_role (role_name, role_code, description, create_at, update_at)
VALUES ('系统管理员', 'ROLE_ADMIN', '管理用户、角色、团队、文档和系统', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
ON CONFLICT (role_code) DO NOTHING;

INSERT INTO kh_role (role_name, role_code, description, create_at, update_at)
VALUES ('审核员', 'ROLE_SH', '审核所属团队授权范围内的知识文档', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
ON CONFLICT (role_code) DO NOTHING;

INSERT INTO kh_role (role_name, role_code, description, create_at, update_at)
VALUES ('普通用户', 'ROLE_USER', '普通用户基础角色', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
ON CONFLICT (role_code) DO NOTHING;
