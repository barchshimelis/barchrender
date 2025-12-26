from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model

User = get_user_model()

class HomeReplicaSmokeTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(username='tester', password='pass')

    def test_home_replica_renders_for_logged_in_user(self):
        self.client.login(username='tester', password='pass')
        resp = self.client.get(reverse('products:products_home'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Get Task')
