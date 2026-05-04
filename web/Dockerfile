FROM nginx:1.25-alpine
COPY . /usr/share/nginx/html
# nginx.conf is mounted from ConfigMap in k8s (see clockapp/k8s/base/configmap-nginx.yaml)
# When running locally without k8s, provide your own nginx.conf
EXPOSE 80
