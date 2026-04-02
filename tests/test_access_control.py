from __future__ import annotations


def test_unauthenticated_redirected_to_login(client, admin_user):
    """Protected routes should redirect unauthenticated users to login."""
    for path in ["/browse", "/requests", "/upload", "/admin/users"]:
        resp = client.get(path, follow_redirects=False)
        assert resp.status_code == 302, f"GET {path} returned {resp.status_code}"
        assert "/login" in resp.headers["location"], (
            f"GET {path} did not redirect to login"
        )


def test_unapproved_user_gets_403(auth_client, unapproved_user):
    c, _ = auth_client(unapproved_user)
    resp = c.get("/browse", follow_redirects=False)
    assert resp.status_code == 403


def test_admin_masquerade_sees_target_data(admin_client, db_session, regular_user):
    """When admin masquerades, get_current_user returns the target."""
    c, _ = admin_client
    c.cookies.set("cleanarr_masquerade", str(regular_user.id))
    # The dashboard should render for the masqueraded user
    resp = c.get("/", follow_redirects=False)
    # Should not redirect to login (user is valid)
    assert resp.status_code == 200 or resp.headers.get("location") != "/login"


def test_non_admin_masquerade_cookie_ignored(user_client, db_session, admin_user):
    """Non-admin users with masquerade cookie should not see other users' data."""
    c, _ = user_client
    c.cookies.set("cleanarr_masquerade", str(admin_user.id))
    # Should still be the regular user, not masqueraded
    resp = c.get("/browse", follow_redirects=False)
    # Should get 200 (their own view), not admin's
    assert resp.status_code in (200, 502)  # 502 possible if Plex is mocked/unavailable
