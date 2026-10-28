import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from api.document import pg_router, update_kh_doc_api
from api.permission import permission_router
from api.publish import publish_router
from api.review import review_router, review_tasks_api
from api.role import del_role_api, role_router, unbind_role_api, update_role_api
from api.team import team_router
from api.user import assign_roles_api, del_user_api, update_user_api, user_roles_api, user_router
from core.security import count_users_with_role, require_admin, require_reviewer_or_admin
from schemas.document import KhDocumentRespDTO, KhDocumentRespDTOUpdate
from schemas.user import AssignRolesDTO, UpdateRoleDTO, UpdateUserDTO


def result_with_scalars(values):
    return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: values, first=lambda: values[0] if values else None))


def route_by_path(router, path, method):
    return next(route for route in router.routes if route.path == path and method in route.methods)


class AdminRouteDependencyTests(unittest.TestCase):
    def assert_route_depends_on(self, router, path, method, dependency):
        route = route_by_path(router, path, method)
        self.assertIn(dependency, {item.call for item in route.dependant.dependencies})

    def test_management_routes_require_admin(self):
        for path, method in (
            ("/user/query_users", "GET"),
            ("/user/assign_roles", "POST"),
            ("/user/create_user", "POST"),
            ("/user/del_user", "DELETE"),
            ("/role/get_roles", "GET"),
            ("/role/add_role", "POST"),
            ("/team/query_team", "GET"),
            ("/team/add_member", "POST"),
            ("/permission/tree", "GET"),
            ("/knowledge_doc/publish", "POST"),
            ("/pg/drop_table", "POST"),
        ):
            router = {
                "/user/": user_router,
                "/role/": role_router,
                "/team/": team_router,
                "/permission/": permission_router,
                "/knowledge_doc/": publish_router,
                "/pg/": pg_router,
            }[next(prefix for prefix in ("/user/", "/role/", "/team/", "/permission/", "/knowledge_doc/", "/pg/") if path.startswith(prefix))]
            with self.subTest(path=path):
                self.assert_route_depends_on(router, path, method, require_admin)

    def test_review_queue_requires_reviewer_or_admin(self):
        self.assert_route_depends_on(review_router, "/review/tasks", "GET", require_reviewer_or_admin)
        self.assert_route_depends_on(review_router, "/review/pending_count", "GET", require_reviewer_or_admin)


class AdminAccessBehaviorTests(unittest.IsolatedAsyncioTestCase):
    async def test_count_users_with_role(self):
        db = SimpleNamespace(execute=AsyncMock(return_value=SimpleNamespace(scalar=lambda: 2)))
        self.assertEqual(await count_users_with_role(db, 'ROLE_ADMIN'), 2)

    async def test_protected_role_cannot_be_deleted_or_renamed(self):
        role = SimpleNamespace(id=1, role_code='ROLE_ADMIN')
        db = SimpleNamespace(get=AsyncMock(return_value=role), execute=AsyncMock())
        with self.assertRaises(HTTPException) as delete_error:
            await del_role_api(role_id=1, db=db, admin_user=SimpleNamespace(id=7))
        self.assertEqual(delete_error.exception.status_code, 400)

        with self.assertRaises(HTTPException) as rename_error:
            await update_role_api(
                role_id=1,
                dto=UpdateRoleDTO(role_code='ROLE_ROOT'),
                db=db,
                admin_user=SimpleNamespace(id=7),
            )
        self.assertEqual(rename_error.exception.status_code, 400)

    async def test_last_admin_cannot_be_unbound(self):
        user = SimpleNamespace(id=7)
        role = SimpleNamespace(id=1, role_code='ROLE_ADMIN')
        db = SimpleNamespace(get=AsyncMock(side_effect=[user, role]), execute=AsyncMock(), commit=AsyncMock())
        with patch('api.role.get_user_role_codes', new=AsyncMock(return_value={'ROLE_ADMIN'})), patch(
            'api.role.count_users_with_role', new=AsyncMock(return_value=1)
        ):
            with self.assertRaises(HTTPException) as denied:
                await unbind_role_api(user_id=7, role_id=1, db=db, admin_user=SimpleNamespace(id=9))
        self.assertEqual(denied.exception.status_code, 400)
        db.commit.assert_not_awaited()

    async def test_last_admin_cannot_lose_role_or_be_deleted(self):
        target = SimpleNamespace(id=8)
        db = SimpleNamespace(get=AsyncMock(return_value=target), execute=AsyncMock(), commit=AsyncMock(), delete=AsyncMock())
        admin = SimpleNamespace(id=7)
        with patch('api.user.get_user_role_codes', new=AsyncMock(return_value={'ROLE_ADMIN'})), patch(
            'api.user.count_users_with_role', new=AsyncMock(return_value=1)
        ):
            with self.assertRaises(HTTPException) as role_error:
                await assign_roles_api(
                    dto=AssignRolesDTO(user_id=8, role_codes=[]), db=db, admin_user=admin
                )
            self.assertEqual(role_error.exception.status_code, 400)

            with self.assertRaises(HTTPException) as delete_error:
                await del_user_api(user_id=8, db=db, admin_user=admin)
            self.assertEqual(delete_error.exception.status_code, 400)
        db.commit.assert_not_awaited()

    async def test_admin_cannot_delete_own_account(self):
        db = SimpleNamespace(get=AsyncMock(return_value=SimpleNamespace(id=7)), execute=AsyncMock(), commit=AsyncMock())
        with self.assertRaises(HTTPException) as denied:
            await del_user_api(user_id=7, db=db, admin_user=SimpleNamespace(id=7))
        self.assertEqual(denied.exception.status_code, 400)
        db.commit.assert_not_awaited()

    async def test_admin_dependency_rejects_non_admin_and_accepts_admin(self):
        user = SimpleNamespace(id=7)
        db = SimpleNamespace(execute=AsyncMock())
        db.execute.return_value = result_with_scalars([])
        with self.assertRaises(HTTPException) as denied:
            await require_admin(db, user)
        self.assertEqual(denied.exception.status_code, 403)

        db.execute.return_value = result_with_scalars(["ROLE_ADMIN"])
        self.assertIs(await require_admin(db, user), user)

    async def test_reviewer_dependency_accepts_reviewer_but_rejects_regular_user(self):
        user = SimpleNamespace(id=7)
        db = SimpleNamespace(execute=AsyncMock())
        db.execute.return_value = result_with_scalars(["ROLE_SH"])
        self.assertIs(await require_reviewer_or_admin(db, user), user)

        db.execute.return_value = result_with_scalars([])
        with self.assertRaises(HTTPException) as denied:
            await require_reviewer_or_admin(db, user)
        self.assertEqual(denied.exception.status_code, 403)

    async def test_user_can_read_own_roles_but_not_another_users_roles(self):
        current_user = SimpleNamespace(id=7)
        db = SimpleNamespace(get=AsyncMock(return_value=object()), execute=AsyncMock())
        db.execute.return_value = result_with_scalars([])
        own = await user_roles_api(user_id=7, db=db, current_user=current_user)
        self.assertEqual(own["user_id"], 7)

        with self.assertRaises(HTTPException) as denied:
            await user_roles_api(user_id=8, db=db, current_user=current_user)
        self.assertEqual(denied.exception.status_code, 403)

    async def test_user_can_update_own_email_but_not_username_or_other_user(self):
        user = SimpleNamespace(
            id=7,
            username="runner",
            password="hash",
            email="old@example.com",
            create_at=None,
            update_at=None,
        )
        db = SimpleNamespace(
            execute=AsyncMock(side_effect=[
                result_with_scalars([]),
                SimpleNamespace(scalar_one_or_none=lambda: None),
            ]),
            get=AsyncMock(return_value=user),
            commit=AsyncMock(),
            refresh=AsyncMock(),
        )
        saved = await update_user_api(
            user_id=7, dto=UpdateUserDTO(email="new@example.com"), db=db, current_user=user
        )
        self.assertEqual(saved.email, "new@example.com")
        db.get.assert_awaited_once()

        db.execute = AsyncMock(return_value=result_with_scalars([]))
        db.get = AsyncMock()
        with self.assertRaises(HTTPException) as denied_field:
            await update_user_api(
                user_id=7, dto=UpdateUserDTO(username="changed"), db=db, current_user=user
            )
        self.assertEqual(denied_field.exception.status_code, 403)
        db.get.assert_not_awaited()

        with self.assertRaises(HTTPException) as denied_target:
            await update_user_api(
                user_id=8, dto=UpdateUserDTO(email="other@example.com"), db=db, current_user=user
            )
        self.assertEqual(denied_target.exception.status_code, 403)

    async def test_reviewer_queue_query_is_limited_to_member_teams(self):
        current_user = SimpleNamespace(id=7)
        db = SimpleNamespace(execute=AsyncMock(side_effect=[
            result_with_scalars(["ROLE_SH"]),
            result_with_scalars(["12"]),
            SimpleNamespace(scalar=lambda: 1),
            SimpleNamespace(all=lambda: []),
        ]))
        result = await review_tasks_api(
            status="pending", page=1, page_size=10, db=db, current_user=current_user
        )
        self.assertEqual(result["total"], 1)
        count_query = db.execute.await_args_list[2].args[0]
        self.assertIn("kh_document.team_id", str(count_query))
        self.assertIn("12", str(count_query.compile().params.values()))

    async def test_document_author_cannot_change_publish_fields(self):
        user = SimpleNamespace(id=7)
        doc = SimpleNamespace(id=31, author_id=7, content_id=31, summary="draft")
        db = SimpleNamespace(
            get=AsyncMock(return_value=doc),
            execute=AsyncMock(return_value=result_with_scalars([])),
        )
        with self.assertRaises(HTTPException) as denied:
            await update_kh_doc_api(
                dto=KhDocumentRespDTOUpdate(status=1), doc_id=31, db=db, current_user=user
            )
        self.assertEqual(denied.exception.status_code, 403)

    async def test_new_document_cannot_supply_its_own_publish_state_or_team(self):
        from api.document import add_doc_api

        user = SimpleNamespace(id=7)
        db = SimpleNamespace(execute=AsyncMock(side_effect=[
            result_with_scalars([]),
            result_with_scalars(["12"]),
        ]))
        created = SimpleNamespace(id=33, content_id=None)
        dto = KhDocumentRespDTO(
            id=999,
            content_id=998,
            title="draft",
            status=1,
            author_id=99,
            team_id=44,
            is_public=1,
        )
        with patch("api.document.create_kh_doc", new=AsyncMock(return_value=created)) as create_doc:
            await add_doc_api(cfg=dto, db=db, current_user=user)
        saved_cfg = create_doc.await_args.args[1]
        self.assertIsNone(saved_cfg.id)
        self.assertIsNone(saved_cfg.content_id)
        self.assertEqual(saved_cfg.author_id, 7)
        self.assertEqual(saved_cfg.team_id, 12)
        self.assertEqual(saved_cfg.status, 0)
        self.assertEqual(saved_cfg.is_public, 0)
        self.assertIsNone(saved_cfg.publish_time)


if __name__ == "__main__":
    unittest.main()
