## ses-smtp-relay

A script which relays email from Amazon AWS SES into a local mail server. No port-forwarding is required thanks to the use of Cloudflare tunnels to proxy inbound SNS traffic.

This is possible because AWS supports receiving mail and transporting it within a HTTP request through the use of [SNS](https://aws.amazon.com/sns/) (Simple Notification Service).

You are still required to host your own mail server, it's just that all the usual pitfalls (security, maintenance, reputation) are overcome thanks to it not being internet-facing. In fact, the entire thing could operate behind a CG-NAT if required.

### Cloud Setup 

You will need a Cloudflare account with the mail domain you wish to use linked. 

You will need an AWS account, and you'll need to apply for SES (Simple Email Service) production access for your domain identity. More details can be found [here](https://docs.aws.amazon.com/ses/latest/dg/request-production-access.html).

| ⚠️ Pay attention to the region you are going to apply for production access, only [certain regions](https://docs.aws.amazon.com/ses/latest/dg/regions.html#region-receive-email) support mail receiving.

From the Cloudflare dashboard, select 'Zero trust', 'Access', then 'Tunnels'. Create a new [tunnel](https://www.cloudflare.com/en-gb/products/tunnel/), name it however you like and then click 'Save'. Note down the Cloudflare tunnel token.

Select the tunnel you just created and under 'Public Hostname', select 'Add public hostname'. Selecting a subdomain is optional, but recommended (ex: `relay.example.com`). Leave path blank. Select type 'HTTP' and for URL enter `ses-proxy-example:8080` (replace `example` with your organisation name). Click save.

Setup the required [AWS MX records](https://docs.aws.amazon.com/ses/latest/dg/receiving-email-mx-record.html#receiving-email-mx-record-links) on your Cloudflare DNS dashboard for receiving mail using SES. 

In the AWS console, create an S3 bucket for temporarily holding mail, make a note of the name of the bucket and apply the following [bucket policy](https://docs.aws.amazon.com/AmazonS3/latest/userguide/access-policy-language-overview.html?icmpid=docs_amazons3_console).

<details>
  <summary>S3 Bucket Policy</summary>

Replace `BUCKET_NAME` with the name of the S3 bucket you have created. 

Replace `AWS_ACCOUNT_ID` with your [AWS account ID](https://docs.aws.amazon.com/IAM/latest/UserGuide/console_account-alias.html).

```
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Sid": "AllowSESPuts",
            "Effect": "Allow",
            "Principal": {
                "Service": "ses.amazonaws.com"
            },
            "Action": "s3:PutObject",
            "Resource": "arn:aws:s3:::BUCKET_NAME/*",
            "Condition": {
                "StringEquals": {
                    "AWS:SourceAccount": "AWS_ACCOUNT_ID"
                }
            }
        }
    ]
}
```
</details>


In the AWS console, create a new [SNS topic](https://docs.aws.amazon.com/sns/latest/dg/sns-create-topic.html). Name it however you like and for the type, choose 'Standard'. Under 'Access policy' apply the following.

<details>
  <summary>SNS Topic Policy</summary>

Replace `AWS_ACCOUNT_ID` with your [AWS account ID](https://docs.aws.amazon.com/IAM/latest/UserGuide/console_account-alias.html).

Replace `TOPIC_NAME` with the name of your SNS topic.

```
{
  "Version": "2008-10-17",
  "Statement": [
    {
      "Sid": "AllowSNSPublish",
      "Effect": "Allow",
      "Principal": {
        "Service": "ses.amazonaws.com"
      },
      "Action": "SNS:Publish",
      "Resource": "arn:aws:sns:us-east-1:AWS_ACCOUNT_ID:TOPIC_NAME",
      "Condition": {
        "StringEquals": {
          "AWS:SourceAccount": "AWS_ACCOUNT_ID"
        },
        "StringLike": {
          "AWS:SourceArn": "arn:aws:ses:*"
        }
      }
    },
    {
      "Sid": "AllowS3Publish",
      "Effect": "Allow",
      "Principal": {
        "Service": "s3.amazonaws.com"
      },
      "Action": "SNS:Publish",
      "Resource": "arn:aws:sns:us-east-1:AWS_ACCOUNT_ID:TOPIC_NAME",
      "Condition": {
        "StringEquals": {
          "AWS:SourceAccount": "AWS_ACCOUNT_ID"
        },
        "StringLike": {
          "AWS:SourceArn": "arn:aws:s3:*"
        }
      }
    }
  ]
}
```
</details>

Under SNS, select 'Topics', select the topic you created and add a [new subscription](https://docs.aws.amazon.com/sns/latest/dg/sns-create-subscribe-endpoint-to-topic.html). Select the protocol 'HTTPS' and for the endpoint, enter the URL you intend to run the relay under, for example `https://relay.example.org`. 

Under SES, select 'Email receiving' and create a new rule set. If you don't see 'Email receiving' under SES, either you have not been approved for production access, or you have selected an [unsupported region](https://docs.aws.amazon.com/ses/latest/dg/regions.html#region-receive-email). Name the ruleset however you like and select it, create a new [receipt rule](https://docs.aws.amazon.com/ses/latest/dg/receiving-email-receipt-rules-console-walkthrough.html). Name the receipt rule 'forward' and click 'Next' until you reach 'Add actions'. Click 'Add new action' and select 'Deliver to S3 bucket'. Under 'S3 Bucket', select the name of the bucket you created earlier. Under 'SNS topic', select the name of the topic you created earlier. Save the rule.

Finally, go to 'Account', 'Access keys' and create a new [Access key](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_credentials_access-keys.html), note down the access key ID and secret. 

### Local Setup

Clone this repo.

```sh
git clone https://github.com/ben-pearce/ses-smtp-relay
```

Copy the example compose YAML files and environment files.

| ⚠️  Repeat for multiple AWS accounts or regions.

```sh
ORG_NAME=example; cp .org.docker-compose.yml.example $ORG_NAME.org.docker-compose.yml && cp .org.env.example $ORG_NAME.org.env && cp .env.example .env
```

Set the Cloudflare tunnel token and Docker network name.

```sh
vi .env
```

Set the AWS credentials, region & SMTP connection details of your local mail server.

```sh
vi example.org.env
```

Bring the relay proxy online.

```sh
chmod +x ./docker-compose.sh && ./docker-compose.sh up -d
```


### Mail Server Setup

You are not required to run any particular type of mail server. It is common to use a self-hosted solution like [mailcow](https://mailcow.email/) or [mail-in-a-box](https://mailinabox.email/), but you may use any standard SMTP-compliant mail server you like.

If you wish to use [AWS SMTP](https://docs.aws.amazon.com/ses/latest/dg/send-using-smtp-programmatically.html) for sending mail, it is important that your mail server supports [relayhosts](https://docs.mailcow.email/manual-guides/Postfix/u_e-postfix-relayhost/).

### Costs

So long as you stay within the AWS [free tier limits](AWS_Free_Tier), you are unlikely to ever incur a cost for running this setup.